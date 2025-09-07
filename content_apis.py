import os
import requests
import logging
from datetime import datetime
from models import SearchLog
from app import db
import trafilatura

class TMDbAPI:
    def __init__(self):
        self.api_key = os.environ.get('TMDB_API_KEY')
        self.base_url = 'https://api.themoviedb.org/3'
        
    def search_content(self, title, content_type):
        """Search for content on TMDb"""
        if not self.api_key:
            logging.warning("TMDb API key not found")
            return None
        
        endpoint = 'search/movie' if content_type == 'movie' else 'search/tv'
        
        params = {
            'api_key': self.api_key,
            'query': title,
            'language': 'en-US'
        }
        
        try:
            response = requests.get(f"{self.base_url}/{endpoint}", params=params)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('results', [])
            
            if results:
                result = results[0]  # Get first result
                
                # Format poster URL
                if result.get('poster_path'):
                    result['poster_path'] = f"https://image.tmdb.org/t/p/w500{result['poster_path']}"
                
                return result
            
        except Exception as e:
            logging.error(f"TMDb API error: {e}")
        
        return None
    
    def get_content_details(self, tmdb_id, content_type):
        """Get detailed information about content"""
        if not self.api_key:
            return None
        
        endpoint = 'movie' if content_type == 'movie' else 'tv'
        
        try:
            response = requests.get(
                f"{self.base_url}/{endpoint}/{tmdb_id}",
                params={'api_key': self.api_key, 'language': 'en-US'}
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logging.error(f"TMDb details API error: {e}")
            return None

def search_content_online(query, api_preference='tavily'):
    """Search for content using web search APIs"""
    if api_preference == 'tavily':
        return search_with_tavily(query)
    elif api_preference == 'brightdata':
        return search_with_brightdata(query)
    else:
        logging.warning(f"Unknown search API preference: {api_preference}")
        return search_with_tavily(query)  # Fallback

def search_with_tavily(query):
    """Search using Tavily API"""
    api_key = os.environ.get('TAVILY_API_KEY')
    if not api_key:
        logging.warning("Tavily API key not found")
        return []
    
    url = "https://api.tavily.com/search"
    
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "include_answer": False,
        "include_images": False,
        "include_raw_content": True,
        "max_results": 10,
        "include_domains": [
            "imdb.com",
            "rottentomatoes.com",
            "metacritic.com",
            "variety.com",
            "entertainment.com",
            "hollywoodreporter.com",
            "deadline.com",
            "goodreads.com"
        ]
    }
    
    start_time = datetime.utcnow()
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        data = response.json()
        results = data.get('results', [])
        
        # Process results to extract content
        processed_results = []
        for result in results:
            processed_result = {
                'title': result.get('title', ''),
                'url': result.get('url', ''),
                'content': result.get('raw_content', ''),
                'snippet': result.get('content', ''),
                'source': 'tavily'
            }
            
            # Extract full text content if available
            if result.get('url'):
                try:
                    full_content = get_website_text_content(result['url'])
                    if full_content:
                        processed_result['content'] = full_content
                except Exception as e:
                    logging.warning(f"Failed to extract content from {result['url']}: {e}")
            
            processed_results.append(processed_result)
        
        # Log search
        execution_time = (datetime.utcnow() - start_time).total_seconds()
        log_search(query, 'tavily', len(results), execution_time)
        
        return processed_results
        
    except Exception as e:
        logging.error(f"Tavily search error: {e}")
        return []

def search_with_brightdata(query):
    """Search using Bright Data API"""
    api_key = os.environ.get('BRIGHTDATA_API_KEY')
    if not api_key:
        logging.warning("Bright Data API key not found")
        return []
    
    # Note: This is a simplified implementation
    # Bright Data typically requires more complex setup
    # This would need to be configured based on their specific API
    
    try:
        # Placeholder implementation
        # In a real implementation, you would use Bright Data's specific endpoints
        logging.info(f"Bright Data search for: {query}")
        
        # For now, fallback to Tavily
        return search_with_tavily(query)
        
    except Exception as e:
        logging.error(f"Bright Data search error: {e}")
        return []

def get_website_text_content(url):
    """Extract text content from a website using trafilatura"""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded)
            return text
    except Exception as e:
        logging.warning(f"Failed to extract content from {url}: {e}")
    
    return None

def log_search(query, api_used, results_count, execution_time, user_id=None):
    """Log search activity"""
    try:
        search_log = SearchLog(
            user_id=user_id,
            query=query,
            api_used=api_used,
            results_count=results_count,
            execution_time=execution_time
        )
        db.session.add(search_log)
        db.session.commit()
    except Exception as e:
        logging.error(f"Failed to log search: {e}")

def check_content_availability(content):
    """Check where content is available for streaming/purchase"""
    # This would integrate with JustWatch API or similar service
    # For now, return placeholder data
    
    availability = {
        'streaming': [],
        'rent': [],
        'buy': [],
        'free': []
    }
    
    # In a real implementation, you would call external APIs like:
    # - JustWatch API
    # - Reelgood API
    # - Or scrape streaming service websites
    
    return availability
