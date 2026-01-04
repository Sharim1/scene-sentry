"""
Content service for TMDb and other APIs
"""
import os
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TMDbService:
    """Service for interacting with TMDb API"""
    
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
    
    def __init__(self):
        self.api_key = os.environ.get("TMDB_API_KEY")
        if not self.api_key:
            logger.warning("TMDB_API_KEY not found, TMDb features will be limited")
    
    def search_content(self, title: str, content_type: str) -> Optional[Dict[str, Any]]:
        """Search for content on TMDb"""
        if not self.api_key:
            return None
        
        endpoint = "search/movie" if content_type == "movie" else "search/tv"
        
        params = {
            "api_key": self.api_key,
            "query": title,
            "language": "en-US"
        }
        
        try:
            response = requests.get(f"{self.BASE_URL}/{endpoint}", params=params)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])
            
            if results:
                result = results[0]
                
                # Format poster URL
                if result.get("poster_path"):
                    result["poster_path"] = f"{self.IMAGE_BASE_URL}{result['poster_path']}"
                
                return result
            
        except Exception as e:
            logger.error(f"TMDb API error: {e}")
        
        return None
    
    def get_content_details(self, tmdb_id: int, content_type: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about content"""
        if not self.api_key:
            return None
        
        endpoint = "movie" if content_type == "movie" else "tv"
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/{endpoint}/{tmdb_id}",
                params={"api_key": self.api_key, "language": "en-US"}
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Format poster URL
            if data.get("poster_path"):
                data["poster_path"] = f"{self.IMAGE_BASE_URL}{data['poster_path']}"
            
            if data.get("backdrop_path"):
                data["backdrop_path"] = f"https://image.tmdb.org/t/p/original{data['backdrop_path']}"
            
            return data
            
        except Exception as e:
            logger.error(f"TMDb details API error: {e}")
            return None
    
    def get_trending(self, content_type: str = "all", time_window: str = "week") -> list:
        """Get trending content"""
        if not self.api_key:
            return []
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/trending/{content_type}/{time_window}",
                params={"api_key": self.api_key}
            )
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])
            
            # Format poster URLs
            for result in results:
                if result.get("poster_path"):
                    result["poster_path"] = f"{self.IMAGE_BASE_URL}{result['poster_path']}"
            
            return results
            
        except Exception as e:
            logger.error(f"TMDb trending API error: {e}")
            return []
    
    def get_upcoming(self, content_type: str = "movie") -> list:
        """Get upcoming releases"""
        if not self.api_key:
            return []
        
        endpoint = "movie/upcoming" if content_type == "movie" else "tv/on_the_air"
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/{endpoint}",
                params={"api_key": self.api_key, "language": "en-US"}
            )
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])
            
            # Format poster URLs
            for result in results:
                if result.get("poster_path"):
                    result["poster_path"] = f"{self.IMAGE_BASE_URL}{result['poster_path']}"
            
            return results
            
        except Exception as e:
            logger.error(f"TMDb upcoming API error: {e}")
            return []

