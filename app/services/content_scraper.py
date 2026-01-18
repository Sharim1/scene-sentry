"""
Content Scraper Service - Scrapes actual movie/TV show data from entertainment websites
Uses web scraping + LLM to extract structured movie/TV data
"""
import os
import re
import json
import logging
import httpx
import random
from typing import Optional, Dict, Any, List
from datetime import datetime
import trafilatura

logger = logging.getLogger(__name__)

# Discovery categories and search variations for finding diverse content
MOVIE_GENRES = [
    "action", "comedy", "drama", "horror", "thriller", "sci-fi", "romance",
    "animation", "documentary", "fantasy", "mystery", "adventure", "crime",
    "family", "musical", "war", "western", "biography", "history", "sport"
]

MOVIE_DISCOVERY_MODES = [
    "upcoming",        # Movies coming soon
    "hidden_gems",     # Underrated/lesser known
    "award_winners",   # Oscar/award winning
    "classic",         # Classic cinema
    "international",   # Foreign films
    "indie",           # Independent films
    "blockbuster",     # Big budget movies
    "critically_acclaimed",  # High critic scores
    "cult_classic",    # Cult following
    "recent_release",  # Just released
]

TV_GENRES = [
    "drama", "comedy", "thriller", "sci-fi", "fantasy", "crime", "mystery",
    "horror", "romance", "action", "adventure", "documentary", "animation",
    "reality", "talk-show", "anthology", "medical", "legal", "superhero"
]

TV_DISCOVERY_MODES = [
    "new_series",      # Just started
    "returning",       # New seasons
    "binge_worthy",    # Great for binging
    "limited_series",  # Miniseries
    "international",   # Foreign shows
    "streaming_hit",   # Popular on streaming
    "hidden_gems",     # Underrated
    "critically_acclaimed",
]


class ContentScraper:
    """
    Scrapes actual movie and TV show data from entertainment websites.
    Uses Tavily for web search but then parses actual content from results,
    and uses Gemini LLM to extract structured movie/TV data.
    """
    
    def __init__(self):
        from app.config import settings
        self.tavily_api_key = settings.tavily_api_key
        self.gemini_api_key = settings.gemini_api_key
        self.http_client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
    
    async def discover_movies(self, preferences: str = "popular", limit: int = 20) -> List[Dict[str, Any]]:
        """
        Discover movies by scraping entertainment websites.
        Uses randomized queries and multiple sources to find diverse content.
        Returns structured movie data with title, poster, rating, etc.
        """
        movies = []
        current_year = datetime.now().year
        
        # Generate varied search queries based on random selections
        discovery_mode = random.choice(MOVIE_DISCOVERY_MODES)
        random_genres = random.sample(MOVIE_GENRES, min(3, len(MOVIE_GENRES)))
        random_year = random.choice([current_year, current_year - 1, current_year - 2, 
                                      random.randint(2000, current_year - 3),
                                      random.randint(1990, 1999),
                                      random.randint(1970, 1989)])
        
        logger.info(f"Movie discovery mode: {discovery_mode}, genres: {random_genres}, year focus: {random_year}")
        
        # Build diverse search queries
        search_queries = self._build_movie_search_queries(
            preferences, discovery_mode, random_genres, random_year, current_year
        )
        
        # Try IMDB charts first - start with reliable moviemeter chart, then try varied sources
        try:
            # First try the reliable moviemeter chart that we know works
            imdb_movies = await self._scrape_imdb_popular_movies()
            if not imdb_movies:
                # Fall back to varied sources if moviemeter fails
                imdb_movies = await self._scrape_imdb_movies_varied(discovery_mode, random_genres)
            
            for movie in imdb_movies:
                if movie.get('title') and not any(
                    m.get('title', '').lower() == movie['title'].lower() for m in movies
                ):
                    movies.append(movie)
            logger.debug(f"IMDB contributed {len(imdb_movies)} movies")
        except Exception as e:
            logger.warning(f"IMDB scraping failed: {e}")
        
        # Try Letterboxd with different filters
        try:
            letterboxd_movies = await self._scrape_letterboxd_varied(discovery_mode, random_genres, random_year)
            for movie in letterboxd_movies:
                if movie.get('title') and not any(
                    m.get('title', '').lower() == movie['title'].lower() for m in movies
                ):
                    movies.append(movie)
        except Exception as e:
            logger.warning(f"Letterboxd scraping failed: {e}")
        
        # Use Tavily with varied queries if we need more
        if len(movies) < limit:
            for query in search_queries[:3]:  # Try up to 3 different queries
                if len(movies) >= limit:
                    break
                try:
                    tavily_movies = await self._scrape_from_tavily_search(query, "movie")
                    for movie in tavily_movies:
                        if movie.get('title') and not any(
                            m.get('title', '').lower() == movie['title'].lower() for m in movies
                        ):
                            movies.append(movie)
                except Exception as e:
                    logger.warning(f"Tavily search failed for '{query}': {e}")
        
        logger.info(f"Movie discovery found {len(movies)} unique movies")
        return movies[:limit]
    
    def _build_movie_search_queries(self, preferences: str, mode: str, genres: List[str], 
                                     year: int, current_year: int) -> List[str]:
        """Build varied search queries based on discovery mode and preferences"""
        queries = []
        
        mode_queries = {
            "upcoming": [
                f"upcoming movies {current_year} {current_year + 1} release date",
                f"most anticipated movies {current_year}",
                f"new movie releases {current_year} trailer",
            ],
            "hidden_gems": [
                f"underrated movies {year} must watch",
                f"best hidden gem movies {random.choice(genres)}",
                f"overlooked movies {year} critically acclaimed",
            ],
            "award_winners": [
                f"oscar winning movies {year} best picture",
                f"award winning {random.choice(genres)} movies",
                f"golden globe best movie {year}",
            ],
            "classic": [
                f"classic {random.choice(genres)} movies must watch",
                f"best movies {random.randint(1950, 1999)} all time",
                f"timeless classic films {random.choice(genres)}",
            ],
            "international": [
                f"best foreign films {year} {random.choice(['korean', 'japanese', 'french', 'spanish', 'indian'])}",
                f"international movies {random.choice(genres)} subtitled",
                f"world cinema {year} award winning",
            ],
            "indie": [
                f"best independent films {year}",
                f"indie movies {random.choice(genres)} {year}",
                f"sundance film festival {year} movies",
            ],
            "blockbuster": [
                f"highest grossing movies {year}",
                f"biggest box office movies {current_year}",
                f"blockbuster {random.choice(genres)} movies",
            ],
            "critically_acclaimed": [
                f"highest rated movies {year} metacritic",
                f"best reviewed {random.choice(genres)} movies",
                f"90%+ rotten tomatoes movies {year}",
            ],
            "cult_classic": [
                f"cult classic movies {random.choice(genres)}",
                f"movies with cult following must watch",
                f"midnight movies cult films",
            ],
            "recent_release": [
                f"movies released this month {current_year}",
                f"new movies in theaters now {current_year}",
                f"latest {random.choice(genres)} movies {current_year}",
            ],
        }
        
        # Add mode-specific queries
        queries.extend(mode_queries.get(mode, [f"best movies {year} {random.choice(genres)}"]))
        
        # Add preference-based queries
        if preferences and preferences != "popular":
            queries.append(f"best {preferences} movies {current_year}")
            queries.append(f"{preferences} movies highly rated")
        
        # Add genre-specific queries
        for genre in genres[:2]:
            queries.append(f"best {genre} movies {random.choice([year, current_year, current_year - 1])}")
        
        # Shuffle to get variety
        random.shuffle(queries)
        return queries
    
    async def discover_tv_shows(self, preferences: str = "popular", limit: int = 20) -> List[Dict[str, Any]]:
        """
        Discover TV shows by scraping entertainment websites.
        Uses randomized queries and multiple sources to find diverse content.
        """
        shows = []
        current_year = datetime.now().year
        
        # Generate varied search parameters
        discovery_mode = random.choice(TV_DISCOVERY_MODES)
        random_genres = random.sample(TV_GENRES, min(3, len(TV_GENRES)))
        random_year = random.choice([current_year, current_year - 1, current_year - 2,
                                      random.randint(2015, current_year - 3)])
        
        logger.info(f"TV discovery mode: {discovery_mode}, genres: {random_genres}, year focus: {random_year}")
        
        # Build diverse search queries
        search_queries = self._build_tv_search_queries(
            preferences, discovery_mode, random_genres, random_year, current_year
        )
        
        # Try IMDB TV charts
        try:
            imdb_shows = await self._scrape_imdb_tv_varied(discovery_mode, random_genres)
            for show in imdb_shows:
                if show.get('title') and not any(
                    s.get('title', '').lower() == show['title'].lower() for s in shows
                ):
                    shows.append(show)
        except Exception as e:
            logger.warning(f"IMDB TV scraping failed: {e}")
        
        # Use Tavily with varied queries
        for query in search_queries[:3]:
            if len(shows) >= limit:
                break
            try:
                tavily_shows = await self._scrape_from_tavily_search(query, "tv_show")
                for show in tavily_shows:
                    if show.get('title') and not any(
                        s.get('title', '').lower() == show['title'].lower() for s in shows
                    ):
                        shows.append(show)
            except Exception as e:
                logger.warning(f"Tavily TV search failed for '{query}': {e}")
        
        logger.info(f"TV discovery found {len(shows)} unique shows")
        return shows[:limit]
    
    def _build_tv_search_queries(self, preferences: str, mode: str, genres: List[str],
                                  year: int, current_year: int) -> List[str]:
        """Build varied search queries for TV shows"""
        queries = []
        
        mode_queries = {
            "new_series": [
                f"new TV series {current_year} premiere",
                f"TV shows starting {current_year}",
                f"new {random.choice(genres)} series {current_year}",
            ],
            "returning": [
                f"TV shows returning {current_year} new season",
                f"best shows renewed {current_year}",
                f"{random.choice(genres)} series new season {current_year}",
            ],
            "binge_worthy": [
                f"best binge worthy TV shows",
                f"addictive TV series {random.choice(genres)}",
                f"TV shows to binge watch {year}",
            ],
            "limited_series": [
                f"best miniseries {year}",
                f"limited series {random.choice(genres)} {year}",
                f"one season TV shows {year}",
            ],
            "international": [
                f"best foreign TV shows {year} {random.choice(['korean', 'british', 'spanish', 'japanese'])}",
                f"international series {random.choice(genres)}",
                f"non-english TV shows {year}",
            ],
            "streaming_hit": [
                f"best {random.choice(['Netflix', 'HBO', 'Apple TV', 'Prime Video', 'Disney+'])} shows {current_year}",
                f"trending streaming shows {current_year}",
                f"most watched streaming series {year}",
            ],
            "hidden_gems": [
                f"underrated TV shows {year}",
                f"overlooked {random.choice(genres)} series",
                f"hidden gem TV shows must watch",
            ],
            "critically_acclaimed": [
                f"highest rated TV shows {year}",
                f"emmy winning series {year}",
                f"best reviewed {random.choice(genres)} shows",
            ],
        }
        
        queries.extend(mode_queries.get(mode, [f"best TV shows {year}"]))
        
        if preferences and preferences != "popular":
            queries.append(f"best {preferences} TV shows {current_year}")
        
        for genre in genres[:2]:
            queries.append(f"best {genre} TV series {random.choice([year, current_year])}")
        
        random.shuffle(queries)
        return queries
    
    async def _scrape_imdb_popular_movies(self) -> List[Dict[str, Any]]:
        """Scrape popular movies from IMDb charts"""
        movies = []
        
        try:
            # IMDb Popular Movies page
            url = "https://www.imdb.com/chart/moviemeter/"
            response = self.http_client.get(url)
            
            if response.status_code == 200:
                movies = self._parse_imdb_chart(response.text, "movie")
                
        except Exception as e:
            logger.error(f"Error scraping IMDb movies: {e}")
        
        return movies
    
    async def _scrape_imdb_movies_varied(self, mode: str, genres: List[str]) -> List[Dict[str, Any]]:
        """Scrape movies from various IMDb pages based on discovery mode"""
        movies = []
        current_year = datetime.now().year
        
        # Map discovery modes to IMDb URLs
        url_options = {
            "upcoming": [
                "https://www.imdb.com/calendar/",
                f"https://www.imdb.com/search/title/?title_type=feature&release_date={current_year}-01-01,{current_year + 1}-12-31&sort=release_date,asc",
            ],
            "hidden_gems": [
                "https://www.imdb.com/search/title/?title_type=feature&num_votes=1000,50000&user_rating=7.0,10&sort=user_rating,desc",
            ],
            "award_winners": [
                "https://www.imdb.com/search/title/?title_type=feature&groups=oscar_winner&sort=year,desc",
                "https://www.imdb.com/search/title/?title_type=feature&groups=oscar_best_picture_winners",
            ],
            "classic": [
                "https://www.imdb.com/chart/top/",
                "https://www.imdb.com/search/title/?title_type=feature&release_date=,1999-12-31&user_rating=8.0,10&sort=user_rating,desc",
            ],
            "blockbuster": [
                "https://www.imdb.com/chart/boxoffice",
                "https://www.imdb.com/search/title/?title_type=feature&sort=boxoffice_gross_us,desc",
            ],
            "critically_acclaimed": [
                "https://www.imdb.com/search/title/?title_type=feature&user_rating=8.0,10&num_votes=100000,&sort=user_rating,desc",
            ],
            "recent_release": [
                "https://www.imdb.com/chart/moviemeter/",
                f"https://www.imdb.com/search/title/?title_type=feature&release_date={current_year - 1}-01-01,{current_year}-12-31&sort=release_date,desc",
            ],
        }
        
        # Genre-based URLs
        genre_map = {
            "action": "action", "comedy": "comedy", "drama": "drama", "horror": "horror",
            "thriller": "thriller", "sci-fi": "sci-fi", "romance": "romance",
            "animation": "animation", "documentary": "documentary", "fantasy": "fantasy",
            "mystery": "mystery", "adventure": "adventure", "crime": "crime",
        }
        
        # Get URLs for this mode
        urls = url_options.get(mode, ["https://www.imdb.com/chart/moviemeter/"])
        
        # Add genre-specific URL if genre matches
        for genre in genres[:1]:
            if genre in genre_map:
                urls.append(f"https://www.imdb.com/search/title/?title_type=feature&genres={genre_map[genre]}&sort=user_rating,desc&num_votes=10000,")
        
        # Pick a random URL from options
        selected_url = random.choice(urls)
        logger.debug(f"IMDB scraping from: {selected_url}")
        
        try:
            response = self.http_client.get(selected_url)
            if response.status_code == 200:
                # Check if it's a chart page or search page
                if '/chart/' in selected_url:
                    movies = self._parse_imdb_chart(response.text, "movie")
                else:
                    movies = self._parse_imdb_search_results(response.text, "movie")
        except Exception as e:
            logger.error(f"Error scraping IMDb varied: {e}")
        
        return movies
    
    async def _scrape_imdb_popular_tv(self) -> List[Dict[str, Any]]:
        """Scrape popular TV shows from IMDb"""
        shows = []
        
        try:
            url = "https://www.imdb.com/chart/tvmeter/"
            response = self.http_client.get(url)
            
            if response.status_code == 200:
                shows = self._parse_imdb_chart(response.text, "tv_show")
                
        except Exception as e:
            logger.error(f"Error scraping IMDb TV: {e}")
        
        return shows
    
    async def _scrape_imdb_tv_varied(self, mode: str, genres: List[str]) -> List[Dict[str, Any]]:
        """Scrape TV shows from various IMDb pages based on discovery mode"""
        shows = []
        current_year = datetime.now().year
        
        url_options = {
            "new_series": [
                f"https://www.imdb.com/search/title/?title_type=tv_series&release_date={current_year}-01-01,{current_year}-12-31&sort=release_date,desc",
            ],
            "returning": [
                "https://www.imdb.com/chart/tvmeter/",
            ],
            "binge_worthy": [
                "https://www.imdb.com/search/title/?title_type=tv_series&user_rating=8.0,10&num_votes=50000,&sort=user_rating,desc",
            ],
            "limited_series": [
                "https://www.imdb.com/search/title/?title_type=tv_miniseries&sort=user_rating,desc&num_votes=5000,",
            ],
            "streaming_hit": [
                "https://www.imdb.com/chart/tvmeter/",
                "https://www.imdb.com/search/title/?title_type=tv_series&release_date=2020-01-01,&sort=num_votes,desc",
            ],
            "critically_acclaimed": [
                "https://www.imdb.com/chart/toptv/",
                "https://www.imdb.com/search/title/?title_type=tv_series&groups=emmy_winner&sort=year,desc",
            ],
        }
        
        urls = url_options.get(mode, ["https://www.imdb.com/chart/tvmeter/"])
        
        # Add genre-specific URL
        genre_map = {"drama": "drama", "comedy": "comedy", "crime": "crime", "thriller": "thriller",
                     "sci-fi": "sci-fi", "fantasy": "fantasy", "horror": "horror", "mystery": "mystery"}
        for genre in genres[:1]:
            if genre in genre_map:
                urls.append(f"https://www.imdb.com/search/title/?title_type=tv_series&genres={genre_map[genre]}&sort=user_rating,desc&num_votes=10000,")
        
        selected_url = random.choice(urls)
        logger.debug(f"IMDB TV scraping from: {selected_url}")
        
        try:
            response = self.http_client.get(selected_url)
            if response.status_code == 200:
                if '/chart/' in selected_url:
                    shows = self._parse_imdb_chart(response.text, "tv_show")
                else:
                    shows = self._parse_imdb_search_results(response.text, "tv_show")
        except Exception as e:
            logger.error(f"Error scraping IMDb TV varied: {e}")
        
        return shows
    
    def _parse_imdb_search_results(self, html: str, content_type: str) -> List[Dict[str, Any]]:
        """Parse IMDb search results page - handles modern IMDB structure"""
        items = []
        
        try:
            # Method 1: Try to extract from __NEXT_DATA__ JSON (modern IMDB uses Next.js)
            next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
            if next_data_match:
                try:
                    next_data = json.loads(next_data_match.group(1))
                    # Navigate through the Next.js data structure
                    page_props = next_data.get('props', {}).get('pageProps', {})
                    
                    # Try different possible paths in the data structure
                    search_results = (
                        page_props.get('searchResults', {}).get('titleResults', {}).get('titleListItems', []) or
                        page_props.get('cmsContext', {}).get('transformedPlacements', {}) or
                        []
                    )
                    
                    if isinstance(search_results, list):
                        for item in search_results[:25]:
                            title = item.get('titleText', '') or item.get('originalTitleText', '') or item.get('title', '')
                            imdb_id = item.get('id', '') or item.get('titleId', '')
                            
                            if title and imdb_id:
                                items.append({
                                    'title': title,
                                    'imdb_id': imdb_id,
                                    'content_type': content_type,
                                    'external_id': imdb_id,
                                    'rating': item.get('ratingSummary', {}).get('aggregateRating'),
                                    'poster_url': item.get('primaryImage', {}).get('url') if item.get('primaryImage') else None,
                                })
                    logger.debug(f"IMDB Next.js data found {len(items)} items")
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Could not parse IMDB Next.js data: {e}")
            
            # Method 2: Try JSON-LD schema data
            if not items:
                json_ld_match = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL)
                if json_ld_match:
                    try:
                        data = json.loads(json_ld_match.group(1))
                        if isinstance(data, dict) and 'itemListElement' in data:
                            for item in data['itemListElement'][:25]:
                                if 'item' in item:
                                    movie = item['item']
                                    url = movie.get('url', '')
                                    imdb_id = url.split('/title/')[-1].rstrip('/') if '/title/' in url else None
                                    if movie.get('name') and imdb_id:
                                        items.append({
                                            'title': movie.get('name', ''),
                                            'imdb_id': imdb_id,
                                            'content_type': content_type,
                                            'external_id': imdb_id,
                                            'poster_url': movie.get('image'),
                                            'rating': float(movie.get('aggregateRating', {}).get('ratingValue', 0)) if movie.get('aggregateRating') else None,
                                        })
                        logger.debug(f"IMDB JSON-LD data found {len(items)} items")
                    except (json.JSONDecodeError, KeyError):
                        pass
            
            # Method 3: Fallback to regex patterns for title links
            if not items:
                # Multiple patterns to try
                patterns = [
                    r'href="/title/(tt\d+)/[^"]*"[^>]*>\s*([^<]+?)\s*</a>',
                    r'data-testid="title"[^>]*>([^<]+)</[^>]*>.*?href="/title/(tt\d+)',
                    r'class="[^"]*titleColumn[^"]*"[^>]*>.*?<a[^>]*href="/title/(tt\d+)/[^"]*"[^>]*>([^<]+)</a>',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
                    if matches:
                        logger.debug(f"IMDB regex pattern matched {len(matches)} items")
                        break
                
                seen_ids = set()
                for match in matches[:50]:
                    # Handle different capture group orders
                    if match[0].startswith('tt'):
                        imdb_id, title = match[0], match[1]
                    else:
                        title, imdb_id = match[0], match[1] if len(match) > 1 else None
                    
                    if not imdb_id or imdb_id in seen_ids:
                        continue
                    seen_ids.add(imdb_id)
                    
                    title = title.strip()
                    if not title or len(title) < 2:
                        continue
                    
                    # Skip navigation/generic links
                    skip_titles = ['see full summary', 'see more', 'more', 'hide', 'show', 
                                   'full cast', 'reviews', 'trivia', 'goofs', 'quotes']
                    if title.lower() in skip_titles:
                        continue
                    
                    items.append({
                        'title': title,
                        'imdb_id': imdb_id,
                        'content_type': content_type,
                        'external_id': imdb_id,
                    })
                    
                    if len(items) >= 20:
                        break
            
            logger.debug(f"IMDB search results parsed: {len(items)} items found")
                    
        except Exception as e:
            logger.error(f"Error parsing IMDb search results: {e}")
        
        return items
    
    def _parse_imdb_chart(self, html: str, content_type: str) -> List[Dict[str, Any]]:
        """Parse IMDb chart HTML to extract content data"""
        items = []
        
        try:
            # Method 1: Try __NEXT_DATA__ JSON (modern IMDB)
            next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
            if next_data_match:
                try:
                    next_data = json.loads(next_data_match.group(1))
                    page_props = next_data.get('props', {}).get('pageProps', {})
                    
                    # Chart pages have different data structures
                    chart_titles = (
                        page_props.get('pageData', {}).get('chartTitles', {}).get('edges', []) or
                        page_props.get('chartTitles', {}).get('edges', []) or
                        []
                    )
                    
                    for edge in chart_titles[:30]:
                        node = edge.get('node', {})
                        title_obj = node.get('item', node)
                        
                        title = (title_obj.get('titleText', {}).get('text') or 
                                title_obj.get('originalTitleText', {}).get('text') or
                                title_obj.get('title', ''))
                        imdb_id = title_obj.get('id', '')
                        
                        if title and imdb_id:
                            poster_url = None
                            if title_obj.get('primaryImage'):
                                poster_url = title_obj['primaryImage'].get('url')
                            
                            rating = None
                            if title_obj.get('ratingsSummary'):
                                rating = title_obj['ratingsSummary'].get('aggregateRating')
                            
                            items.append({
                                'title': title,
                                'imdb_id': imdb_id,
                                'content_type': content_type,
                                'external_id': imdb_id,
                                'poster_url': poster_url,
                                'rating': rating,
                            })
                    
                    if items:
                        logger.debug(f"IMDB chart Next.js data: found {len(items)} items")
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Could not parse IMDB chart Next.js data: {e}")
            
            # Method 2: Extract JSON-LD data if available
            if not items:
                json_ld_match = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL)
                if json_ld_match:
                    try:
                        data = json.loads(json_ld_match.group(1))
                        if isinstance(data, dict) and 'itemListElement' in data:
                            for item in data['itemListElement'][:25]:
                                if 'item' in item:
                                    movie = item['item']
                                    url = movie.get('url', '')
                                    imdb_id = url.split('/title/')[-1].rstrip('/') if '/title/' in url else None
                                    if movie.get('name'):
                                        items.append({
                                            'title': movie.get('name', ''),
                                            'poster_url': movie.get('image', ''),
                                            'rating': float(movie.get('aggregateRating', {}).get('ratingValue', 0)) if movie.get('aggregateRating') else None,
                                            'imdb_id': imdb_id,
                                            'external_id': imdb_id,
                                            'description': movie.get('description', ''),
                                            'content_type': content_type,
                                        })
                            logger.debug(f"IMDB chart JSON-LD: found {len(items)} items")
                    except json.JSONDecodeError:
                        pass
            
            # Method 3: Fallback to regex parsing
            if not items:
                # Look for title patterns with IMDb IDs
                title_pattern = r'href="/title/(tt\d+)/[^"]*"[^>]*>([^<]+)</a>'
                matches = re.findall(title_pattern, html)
                
                # Filter out non-title links
                seen_ids = set()
                for imdb_id, title in matches:
                    if imdb_id in seen_ids:
                        continue
                    
                    title = title.strip()
                    # Skip navigation/meta links
                    if not title or len(title) < 2 or title.lower() in ['see more', 'more', 'full cast']:
                        continue
                    
                    seen_ids.add(imdb_id)
                    items.append({
                        'title': title,
                        'imdb_id': imdb_id,
                        'content_type': content_type,
                        'external_id': imdb_id,
                    })
                    
                    if len(items) >= 25:
                        break
                
                if items:
                    logger.debug(f"IMDB chart regex fallback: found {len(items)} items")
                    
        except Exception as e:
            logger.error(f"Error parsing IMDb chart: {e}")
        
        logger.debug(f"IMDB chart total parsed: {len(items)} items")
        return items
    
    async def _scrape_letterboxd_popular(self) -> List[Dict[str, Any]]:
        """Scrape popular films from Letterboxd"""
        movies = []
        
        try:
            url = "https://letterboxd.com/films/popular/this/week/"
            response = self.http_client.get(url)
            
            if response.status_code == 200:
                movies = self._parse_letterboxd_page(response.text)
                    
        except Exception as e:
            logger.error(f"Error scraping Letterboxd: {e}")
        
        return movies
    
    async def _scrape_letterboxd_varied(self, mode: str, genres: List[str], year: int) -> List[Dict[str, Any]]:
        """Scrape films from various Letterboxd pages based on discovery mode"""
        movies = []
        current_year = datetime.now().year
        
        # Letterboxd URL patterns
        url_options = {
            "upcoming": [
                f"https://letterboxd.com/films/popular/upcoming/",
                f"https://letterboxd.com/films/year/{current_year}/",
            ],
            "hidden_gems": [
                "https://letterboxd.com/films/popular/this/year/size/small/",
                f"https://letterboxd.com/films/decade/{(year // 10) * 10}s/by/rating/size/small/",
            ],
            "award_winners": [
                "https://letterboxd.com/films/by/rating/",
                "https://letterboxd.com/films/popular/this/year/",
            ],
            "classic": [
                f"https://letterboxd.com/films/decade/{random.choice(['1970s', '1980s', '1990s', '2000s'])}/by/rating/",
                "https://letterboxd.com/films/by/rating/",
            ],
            "international": [
                f"https://letterboxd.com/films/country/{random.choice(['south-korea', 'japan', 'france', 'india', 'spain'])}/by/rating/",
            ],
            "indie": [
                "https://letterboxd.com/films/popular/this/year/size/small/",
            ],
            "blockbuster": [
                "https://letterboxd.com/films/popular/this/week/",
                "https://letterboxd.com/films/popular/this/month/",
            ],
            "critically_acclaimed": [
                "https://letterboxd.com/films/by/rating/",
                f"https://letterboxd.com/films/year/{current_year}/by/rating/",
            ],
            "cult_classic": [
                "https://letterboxd.com/films/genre/cult/by/rating/",
            ],
            "recent_release": [
                f"https://letterboxd.com/films/year/{current_year}/by/popular/",
                f"https://letterboxd.com/films/year/{current_year - 1}/by/popular/",
            ],
        }
        
        # Genre-specific URLs
        letterboxd_genres = {
            "action": "action", "comedy": "comedy", "drama": "drama", "horror": "horror",
            "thriller": "thriller", "sci-fi": "science-fiction", "romance": "romance",
            "animation": "animation", "documentary": "documentary", "fantasy": "fantasy",
            "mystery": "mystery", "adventure": "adventure", "crime": "crime",
        }
        
        urls = url_options.get(mode, ["https://letterboxd.com/films/popular/this/week/"])
        
        # Add genre-specific URLs
        for genre in genres[:1]:
            if genre in letterboxd_genres:
                urls.append(f"https://letterboxd.com/films/genre/{letterboxd_genres[genre]}/by/rating/")
        
        # Add year-specific URL
        urls.append(f"https://letterboxd.com/films/year/{year}/by/popular/")
        
        selected_url = random.choice(urls)
        logger.debug(f"Letterboxd scraping from: {selected_url}")
        
        try:
            response = self.http_client.get(selected_url)
            if response.status_code == 200:
                movies = self._parse_letterboxd_page(response.text)
        except Exception as e:
            logger.error(f"Error scraping Letterboxd varied: {e}")
        
        return movies
    
    def _parse_letterboxd_page(self, html: str) -> List[Dict[str, Any]]:
        """Parse a Letterboxd page to extract movie data"""
        movies = []
        
        try:
            # Method 1: Try data-film-slug pattern with poster
            poster_pattern = r'data-film-slug="([^"]+)"[^>]*>.*?<img[^>]*src="(https://[^"]+)"[^>]*alt="([^"]+)"'
            matches = re.findall(poster_pattern, html, re.DOTALL)
            
            if matches:
                logger.debug(f"Letterboxd pattern 1 found {len(matches)} films")
                for slug, poster_url, title in matches[:25]:
                    hi_res_poster = poster_url.replace('-0-150-0-225-', '-0-500-0-750-').replace('-0-70-0-105-', '-0-500-0-750-')
                    movies.append({
                        'title': title.strip(),
                        'poster_url': hi_res_poster,
                        'content_type': 'movie',
                        'external_id': f'letterboxd_{slug}',
                    })
            
            # Method 2: Alternative pattern - look for film poster links
            if not movies:
                alt_pattern = r'<div[^>]*class="[^"]*film-poster[^"]*"[^>]*data-film-slug="([^"]+)"[^>]*>.*?alt="([^"]+)"'
                alt_matches = re.findall(alt_pattern, html, re.DOTALL)
                if alt_matches:
                    logger.debug(f"Letterboxd pattern 2 found {len(alt_matches)} films")
                    for slug, title in alt_matches[:25]:
                        movies.append({
                            'title': title.strip(),
                            'content_type': 'movie',
                            'external_id': f'letterboxd_{slug}',
                        })
            
            # Method 3: Look for film links with data-film-id
            if not movies:
                id_pattern = r'data-film-id="(\d+)"[^>]*data-film-slug="([^"]+)"'
                title_pattern = r'alt="([^"]+)"[^>]*class="[^"]*image[^"]*"'
                
                id_matches = re.findall(id_pattern, html)
                title_matches = re.findall(title_pattern, html)
                
                if id_matches:
                    logger.debug(f"Letterboxd pattern 3 found {len(id_matches)} film IDs")
                    for i, (film_id, slug) in enumerate(id_matches[:25]):
                        title = title_matches[i] if i < len(title_matches) else slug.replace('-', ' ').title()
                        movies.append({
                            'title': title.strip(),
                            'content_type': 'movie',
                            'external_id': f'letterboxd_{slug}',
                        })
            
            # Method 4: Simple slug extraction as last resort
            if not movies:
                slug_pattern = r'data-film-slug="([^"]+)"'
                slugs = re.findall(slug_pattern, html)
                if slugs:
                    logger.debug(f"Letterboxd pattern 4 found {len(slugs)} slugs")
                    seen = set()
                    for slug in slugs[:30]:
                        if slug in seen:
                            continue
                        seen.add(slug)
                        # Convert slug to title (e.g., "the-godfather" -> "The Godfather")
                        title = slug.replace('-', ' ').title()
                        movies.append({
                            'title': title,
                            'content_type': 'movie',
                            'external_id': f'letterboxd_{slug}',
                        })
                        if len(movies) >= 25:
                            break
            
            logger.debug(f"Letterboxd parsed: {len(movies)} movies found")
            
        except Exception as e:
            logger.error(f"Error parsing Letterboxd page: {e}")
        
        return movies
    
    async def _scrape_from_tavily_search(self, query: str, content_type: str) -> List[Dict[str, Any]]:
        """
        Use Tavily to search and then extract structured content using LLM.
        This is a fallback that uses AI to parse search results into movie/TV data.
        """
        items = []
        
        if not self.tavily_api_key:
            logger.warning("Tavily API key not configured")
            return items
        
        try:
            from tavily import TavilyClient
            tavily = TavilyClient(api_key=self.tavily_api_key)
            
            # Search with specific domains for better results - focus on content databases
            search_results = tavily.search(
                query=query,
                search_depth="advanced",
                max_results=10,
                include_domains=[
                    "imdb.com",
                    "rottentomatoes.com", 
                    "letterboxd.com",
                    "metacritic.com",
                    "themoviedb.org",
                    "tvmaze.com",
                    "thetvdb.com",
                ],
                exclude_domains=[
                    "variety.com",
                    "deadline.com",
                    "hollywoodreporter.com",
                    "collider.com",
                    "screenrant.com",
                    "cinemablend.com",
                    "ew.com",
                    "indiewire.com",
                    "twitter.com",
                    "reddit.com",
                ]
            )
            
            # Process each result to extract movie/show data
            for result in search_results.get('results', []):
                url = result.get('url', '')
                title = result.get('title', '')
                content = result.get('content', '')
                
                # Skip if URL looks like an article/list page
                if self._is_article_url(url):
                    continue
                
                # Try to extract from IMDb pages
                if 'imdb.com/title/' in url:
                    item = await self._extract_from_imdb_url(url, content_type)
                    if item and self._is_valid_content_title(item.get('title', '')):
                        items.append(item)
                
                # Try to extract from Rotten Tomatoes
                elif 'rottentomatoes.com' in url and ('/m/' in url or '/tv/' in url):
                    item = self._extract_from_rt_result(result, content_type)
                    if item and self._is_valid_content_title(item.get('title', '')):
                        items.append(item)
                
                # Skip LLM extraction for non-content pages
                elif 'themoviedb.org' in url or 'tvmaze.com' in url or 'thetvdb.com' in url:
                    extracted = await self._extract_with_llm(result, content_type)
                    for item in extracted:
                        if self._is_valid_content_title(item.get('title', '')):
                            items.append(item)
                    
        except Exception as e:
            logger.error(f"Tavily scraping error: {e}")
        
        return items
    
    def _is_article_url(self, url: str) -> bool:
        """Check if URL looks like an article/list page rather than a content page"""
        article_indicators = [
            '/news/', '/article/', '/blog/', '/list/', '/feature/',
            '/best-', '/top-', '/guide/', '/review/', '/reviews/',
            '/coming-soon', '/streaming-', '/what-to-watch',
            'best-movies', 'best-shows', 'top-movies', 'top-shows',
        ]
        url_lower = url.lower()
        return any(indicator in url_lower for indicator in article_indicators)
    
    def _is_valid_content_title(self, title: str) -> bool:
        """Check if a title looks like a valid movie/TV show title"""
        if not title or len(title) < 2:
            return False
        
        # Import the is_article_title function for validation
        try:
            from app.routes.content import is_article_title
            return not is_article_title(title)
        except ImportError:
            # Fallback basic validation
            title_lower = title.lower()
            invalid_patterns = [
                'best ', 'top ', 'new ', 'upcoming ', 'guide',
                'review', 'recap', 'explained', 'watch ', 'stream',
                'exclusive', 'breaking', 'report', 'announce',
            ]
            return not any(p in title_lower for p in invalid_patterns)
    
    async def _extract_from_imdb_url(self, url: str, content_type: str) -> Optional[Dict[str, Any]]:
        """Extract movie/show data from an IMDb URL"""
        try:
            # Extract IMDb ID
            imdb_match = re.search(r'/title/(tt\d+)', url)
            if not imdb_match:
                return None
            
            imdb_id = imdb_match.group(1)
            
            # Fetch the page
            response = self.http_client.get(url)
            if response.status_code != 200:
                return None
            
            html = response.text
            
            # Extract title
            title_match = re.search(r'<title>([^<]+)</title>', html)
            title = title_match.group(1).split(' - IMDb')[0].split(' (')[0].strip() if title_match else None
            
            # Extract rating
            rating_match = re.search(r'"aggregateRating":\s*\{[^}]*"ratingValue":\s*"?(\d+\.?\d*)"?', html)
            rating = float(rating_match.group(1)) if rating_match else None
            
            # Extract poster
            poster_match = re.search(r'"image":\s*"(https://m\.media-amazon\.com/images/[^"]+)"', html)
            poster_url = poster_match.group(1) if poster_match else None
            
            # Extract description
            desc_match = re.search(r'"description":\s*"([^"]+)"', html)
            description = desc_match.group(1) if desc_match else None
            
            # Extract year
            year_match = re.search(r'"datePublished":\s*"(\d{4})', html)
            release_date = year_match.group(1) if year_match else None
            
            if title:
                return {
                    'title': title,
                    'imdb_id': imdb_id,
                    'poster_url': poster_url,
                    'rating': rating,
                    'description': description,
                    'release_date': release_date,
                    'content_type': content_type,
                }
                
        except Exception as e:
            logger.error(f"Error extracting from IMDb: {e}")
        
        return None
    
    def _extract_from_rt_result(self, result: Dict, content_type: str) -> Optional[Dict[str, Any]]:
        """Extract movie/show data from Rotten Tomatoes search result"""
        try:
            url = result.get('url', '')
            title = result.get('title', '')
            
            # Extract title from URL or title field
            if '/m/' in url or '/tv/' in url:
                # Clean title
                clean_title = title.split(' - Rotten')[0].split(' | ')[0].strip()
                
                # Extract rating from content if available
                content = result.get('content', '')
                rating_match = re.search(r'(\d{1,3})%', content)
                rating = float(rating_match.group(1)) / 10 if rating_match else None
                
                return {
                    'title': clean_title,
                    'rating': rating,
                    'content_type': content_type,
                    'external_id': f'rt_{url.split("/")[-1]}',
                }
                
        except Exception as e:
            logger.error(f"Error extracting from RT: {e}")
        
        return None
    
    async def _extract_with_llm(self, result: Dict, content_type: str) -> List[Dict[str, Any]]:
        """
        Use Gemini LLM to extract structured movie/TV data from search result content.
        """
        items = []
        
        if not self.gemini_api_key:
            return items
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            content = result.get('content', '') or result.get('raw_content', '')
            if not content or len(content) < 100:
                return items
            
            content_label = "movies" if content_type == "movie" else "TV shows/series"
            
            prompt = f"""Extract ONLY actual {content_label} titles from this text.

STRICT RULES:
1. Only extract REAL, SPECIFIC {content_label} titles (e.g., "The Matrix", "Breaking Bad", "Oppenheimer")
2. DO NOT include:
   - Article headlines or list titles (e.g., "Best Movies of 2024", "Top 10 Shows to Watch")
   - News about shows (e.g., "'Show Name' Gets Renewed", "Movie Announces Cast")
   - Generic descriptions (e.g., "new thriller", "upcoming drama")
   - Franchise/series names without specific entry (e.g., "Marvel movies" - too vague)
3. Each title should be a standalone, released or announced {content_label.replace('s', '')} that someone could look up

Return a JSON array with ONLY valid titles:
[
  {{"title": "Exact Title Here", "rating": 8.5, "release_date": "2024", "description": "Brief plot description"}}
]

If no valid {content_label} titles are found, return: []

Text to analyze:
{content[:2500]}

Return ONLY the JSON array, nothing else:"""

            response = model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean response
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json?\n?', '', response_text)
                response_text = re.sub(r'\n?```$', '', response_text)
            
            extracted = json.loads(response_text)
            
            if isinstance(extracted, list):
                for item in extracted[:5]:  # Limit per result
                    title = item.get('title', '').strip()
                    # Additional validation
                    if title and len(title) >= 2 and len(title) <= 60:
                        # Check title doesn't look like an article
                        if self._is_valid_content_title(title):
                            items.append({
                                'title': title,
                                'rating': item.get('rating'),
                                'release_date': str(item.get('release_date', '')) if item.get('release_date') else None,
                                'description': item.get('description'),
                                'content_type': content_type,
                            })
                        
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")
        except Exception as e:
            logger.error(f"LLM extraction error: {e}")
        
        return items
    
    async def get_poster_from_search(self, title: str, content_type: str) -> Optional[str]:
        """
        Try to find a poster URL for a title using image search.
        """
        if not self.tavily_api_key:
            return None
        
        try:
            from tavily import TavilyClient
            tavily = TavilyClient(api_key=self.tavily_api_key)
            
            search_query = f"{title} {'movie' if content_type == 'movie' else 'TV series'} poster"
            
            results = tavily.search(
                query=search_query,
                search_depth="basic",
                max_results=3,
                include_images=True,
            )
            
            # Check for images in results
            images = results.get('images', [])
            if images:
                return images[0]
            
            # Try to extract from result URLs
            for result in results.get('results', []):
                url = result.get('url', '')
                if 'imdb.com/title/' in url:
                    item = await self._extract_from_imdb_url(url, content_type)
                    if item and item.get('poster_url'):
                        return item['poster_url']
                        
        except Exception as e:
            logger.error(f"Poster search error: {e}")
        
        return None
    
    def close(self):
        """Close HTTP client"""
        self.http_client.close()


# Singleton instance
_scraper: Optional[ContentScraper] = None


def get_content_scraper() -> ContentScraper:
    """Get or create the content scraper singleton"""
    global _scraper
    if _scraper is None:
        _scraper = ContentScraper()
    return _scraper

