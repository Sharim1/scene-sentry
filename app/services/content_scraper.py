"""
Content Scraper Service - Scrapes actual movie/TV show data from entertainment websites
Uses web scraping + LLM to extract structured movie/TV data
"""
import os
import re
import json
import logging
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime
import trafilatura

logger = logging.getLogger(__name__)


class ContentScraper:
    """
    Scrapes actual movie and TV show data from entertainment websites.
    Uses Tavily for web search but then parses actual content from results,
    and uses Gemini LLM to extract structured movie/TV data.
    """
    
    def __init__(self):
        self.tavily_api_key = os.environ.get("TAVILY_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.http_client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
    
    async def discover_movies(self, preferences: str = "popular", limit: int = 20) -> List[Dict[str, Any]]:
        """
        Discover movies by scraping entertainment websites.
        Returns structured movie data with title, poster, rating, etc.
        """
        movies = []
        
        # Try multiple sources for better coverage
        sources = [
            self._scrape_imdb_popular_movies,
            self._scrape_letterboxd_popular,
            self._scrape_from_tavily_search,
        ]
        
        for source_func in sources:
            try:
                if source_func == self._scrape_from_tavily_search:
                    results = await source_func(f"best new movies 2024 2025 {preferences}", "movie")
                else:
                    results = await source_func()
                
                for movie in results:
                    # Deduplicate by title
                    if movie.get('title') and not any(
                        m.get('title', '').lower() == movie['title'].lower() 
                        for m in movies
                    ):
                        movies.append(movie)
                
                if len(movies) >= limit:
                    break
                    
            except Exception as e:
                logger.warning(f"Source {source_func.__name__} failed: {e}")
                continue
        
        return movies[:limit]
    
    async def discover_tv_shows(self, preferences: str = "popular", limit: int = 20) -> List[Dict[str, Any]]:
        """
        Discover TV shows by scraping entertainment websites.
        Returns structured TV show data.
        """
        shows = []
        
        sources = [
            self._scrape_imdb_popular_tv,
            self._scrape_from_tavily_search,
        ]
        
        for source_func in sources:
            try:
                if source_func == self._scrape_from_tavily_search:
                    results = await source_func(f"best TV shows series 2024 2025 {preferences} streaming", "tv_show")
                else:
                    results = await source_func()
                
                for show in results:
                    if show.get('title') and not any(
                        s.get('title', '').lower() == show['title'].lower() 
                        for s in shows
                    ):
                        shows.append(show)
                
                if len(shows) >= limit:
                    break
                    
            except Exception as e:
                logger.warning(f"Source {source_func.__name__} failed: {e}")
                continue
        
        return shows[:limit]
    
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
    
    def _parse_imdb_chart(self, html: str, content_type: str) -> List[Dict[str, Any]]:
        """Parse IMDb chart HTML to extract content data"""
        items = []
        
        try:
            # Extract JSON-LD data if available (IMDb includes this)
            json_ld_match = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL)
            if json_ld_match:
                try:
                    data = json.loads(json_ld_match.group(1))
                    if isinstance(data, dict) and 'itemListElement' in data:
                        for item in data['itemListElement'][:25]:
                            if 'item' in item:
                                movie = item['item']
                                items.append({
                                    'title': movie.get('name', ''),
                                    'poster_url': movie.get('image', ''),
                                    'rating': float(movie.get('aggregateRating', {}).get('ratingValue', 0)) if movie.get('aggregateRating') else None,
                                    'imdb_id': movie.get('url', '').split('/title/')[-1].rstrip('/') if '/title/' in movie.get('url', '') else None,
                                    'description': movie.get('description', ''),
                                    'content_type': content_type,
                                })
                except json.JSONDecodeError:
                    pass
            
            # Fallback: Parse HTML directly
            if not items:
                # Look for title patterns
                title_pattern = r'<a[^>]*href="/title/(tt\d+)[^"]*"[^>]*>([^<]+)</a>'
                matches = re.findall(title_pattern, html)
                
                # Look for rating patterns
                rating_pattern = r'data-testid="ratingGroup--imdb-rating"[^>]*>.*?(\d+\.?\d*)'
                ratings = re.findall(rating_pattern, html, re.DOTALL)
                
                # Look for poster patterns
                poster_pattern = r'<img[^>]*src="(https://m\.media-amazon\.com/images/[^"]+)"[^>]*>'
                posters = re.findall(poster_pattern, html)
                
                for i, (imdb_id, title) in enumerate(matches[:25]):
                    item = {
                        'title': title.strip(),
                        'imdb_id': imdb_id,
                        'content_type': content_type,
                        'poster_url': posters[i] if i < len(posters) else None,
                        'rating': float(ratings[i]) if i < len(ratings) else None,
                    }
                    items.append(item)
                    
        except Exception as e:
            logger.error(f"Error parsing IMDb chart: {e}")
        
        return items
    
    async def _scrape_letterboxd_popular(self) -> List[Dict[str, Any]]:
        """Scrape popular films from Letterboxd"""
        movies = []
        
        try:
            url = "https://letterboxd.com/films/popular/this/week/"
            response = self.http_client.get(url)
            
            if response.status_code == 200:
                # Parse Letterboxd HTML
                poster_pattern = r'data-film-slug="([^"]+)"[^>]*>.*?<img[^>]*src="(https://[^"]+)"[^>]*alt="([^"]+)"'
                matches = re.findall(poster_pattern, response.text, re.DOTALL)
                
                for slug, poster_url, title in matches[:25]:
                    # Get higher resolution poster
                    hi_res_poster = poster_url.replace('-0-150-0-225-', '-0-500-0-750-').replace('-0-70-0-105-', '-0-500-0-750-')
                    
                    movies.append({
                        'title': title.strip(),
                        'poster_url': hi_res_poster,
                        'content_type': 'movie',
                        'external_id': f'letterboxd_{slug}',
                    })
                    
        except Exception as e:
            logger.error(f"Error scraping Letterboxd: {e}")
        
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
            
            # Search with specific domains for better results
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
                ]
            )
            
            # Process each result to extract movie/show data
            for result in search_results.get('results', []):
                url = result.get('url', '')
                title = result.get('title', '')
                content = result.get('content', '')
                
                # Try to extract from IMDb pages
                if 'imdb.com/title/' in url:
                    item = await self._extract_from_imdb_url(url, content_type)
                    if item:
                        items.append(item)
                
                # Try to extract from Rotten Tomatoes
                elif 'rottentomatoes.com' in url:
                    item = self._extract_from_rt_result(result, content_type)
                    if item:
                        items.append(item)
                
                # Use LLM to extract from other results
                else:
                    extracted = await self._extract_with_llm(result, content_type)
                    items.extend(extracted)
                    
        except Exception as e:
            logger.error(f"Tavily scraping error: {e}")
        
        return items
    
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
            
            prompt = f"""Extract individual {content_type.replace('_', ' ')}s from this text. 
Return a JSON array of objects with these fields:
- title: The exact title of the movie/show
- rating: Numerical rating out of 10 (if mentioned)
- release_date: Year or date (if mentioned)
- description: Brief description (if available)

Only include items that are clearly individual titles, not articles or lists about the industry.
If no clear titles are found, return an empty array [].

Text:
{content[:3000]}

Return ONLY valid JSON array, no other text:"""

            response = model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean response
            if response_text.startswith('```'):
                response_text = re.sub(r'^```json?\n?', '', response_text)
                response_text = re.sub(r'\n?```$', '', response_text)
            
            extracted = json.loads(response_text)
            
            if isinstance(extracted, list):
                for item in extracted[:5]:  # Limit per result
                    if item.get('title') and len(item['title']) > 2:
                        items.append({
                            'title': item['title'],
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

