import os
import json
import logging
from google import genai
from google.genai import types
from app import db
from models import User, Content, Recommendation, SearchLog
from content_apis import TMDbAPI, search_content_online
from datetime import datetime
import re

class RecommendationAgent:
    def __init__(self):
        try:
            self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
            self.tmdb = TMDbAPI()
        except Exception as e:
            logging.error(f"Error initializing RecommendationAgent: {e}")
            self.client = None
            self.tmdb = None
        
    def analyze_user_preferences(self, user):
        """Analyze user's library to understand preferences"""
        library_items = user.library_items
        
        if not library_items:
            return {
                'preferred_genres': [],
                'preferred_decades': [],
                'content_types': ['movie', 'tv_show', 'book'],
                'analysis': "New user - no preference data available"
            }
        
        # Collect data from user's library
        genres = []
        decades = []
        content_types = []
        titles = []
        
        for item in library_items:
            if item.status in ['confirmed', 'in_progress', 'finished'] and item.rating and item.rating >= 4:
                content = item.content
                titles.append(content.title)
                content_types.append(content.content_type)
                
                if content.genres:
                    try:
                        content_genres = json.loads(content.genres)
                        genres.extend(content_genres)
                    except:
                        pass
                
                if content.release_date:
                    try:
                        year = int(content.release_date[:4])
                        decade = (year // 10) * 10
                        decades.append(decade)
                    except:
                        pass
        
        # Use AI to analyze preferences
        analysis_prompt = f"""
        Analyze this user's entertainment preferences based on their highly-rated content:
        
        Titles they enjoyed: {', '.join(titles[:10])}
        Content types: {', '.join(set(content_types))}
        Genres: {', '.join(set(genres))}
        
        Provide a concise analysis of their preferences and suggest what types of content they might enjoy.
        Focus on themes, genres, and content characteristics.
        """
        
        try:
            if not self.client:
                analysis = "AI service unavailable"
            else:
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=analysis_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=500
                    )
                )
                analysis = response.text if response.text else "Unable to analyze preferences"
        except Exception as e:
            logging.error(f"Error analyzing preferences: {e}")
            analysis = f"AI analysis temporarily unavailable - using basic preference matching"
        
        return {
            'preferred_genres': list(set(genres)),
            'preferred_decades': list(set(decades)),
            'content_types': list(set(content_types)),
            'analysis': analysis
        }
    
    def search_and_analyze_content(self, query, user):
        """Search for content and analyze for recommendations"""
        preferences = self.analyze_user_preferences(user)
        
        # Search using selected API
        search_results = search_content_online(query, user.search_api_preference)
        
        recommendations = []
        
        for result in search_results[:10]:  # Limit to top 10 results
            # Extract content information
            content_info = self.extract_content_info(result, preferences)
            
            if content_info:
                # Create or get content record
                content = self.get_or_create_content(content_info)
                
                if content:
                    # Generate recommendation reasoning
                    reasoning = self.generate_recommendation_reasoning(content, preferences, result)
                    
                    # Calculate confidence score
                    confidence = self.calculate_confidence_score(content, preferences)
                    
                    # Create recommendation
                    recommendation = Recommendation(
                        user_id=user.id,
                        content_id=content.id,
                        confidence_score=confidence,
                        reasoning=reasoning,
                        source_urls=json.dumps([result.get('url', '')])
                    )
                    
                    db.session.add(recommendation)
                    recommendations.append(recommendation)
        
        db.session.commit()
        return recommendations
    
    def extract_content_info(self, search_result, preferences):
        """Extract structured content information from search results"""
        text = search_result.get('content', '')
        title = search_result.get('title', '')
        
        # Use AI to extract content information
        extraction_prompt = f"""
        Extract entertainment content information from this text:
        
        Title: {title}
        Content: {text[:1000]}
        
        Identify if this is about a movie, TV show, or book. Extract:
        - Title
        - Content type (movie, tv_show, or book)
        - Release year
        - Genre(s)
        - Brief description
        - Director/Author (if mentioned)
        
        Respond in JSON format:
        {{
            "title": "Title",
            "content_type": "movie|tv_show|book",
            "release_year": "YYYY",
            "genres": ["genre1", "genre2"],
            "description": "Brief description",
            "creator": "Director or Author name"
        }}
        
        If this is not about entertainment content, return null.
        """
        
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=extraction_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            if response.text:
                content_info = json.loads(response.text)
                if content_info and content_info.get('title'):
                    return content_info
        except Exception as e:
            logging.error(f"Error extracting content info: {e}")
        
        return None
    
    def get_or_create_content(self, content_info):
        """Get existing content or create new record"""
        title = content_info.get('title', '').strip()
        content_type = content_info.get('content_type', '').strip()
        
        if not title or not content_type:
            return None
        
        # Check if content already exists
        existing = Content.query.filter_by(
            title=title,
            content_type=content_type
        ).first()
        
        if existing:
            return existing
        
        # Get additional metadata from TMDb if it's a movie or TV show
        tmdb_data = None
        if content_type in ['movie', 'tv_show']:
            tmdb_data = self.tmdb.search_content(title, content_type)
        
        # Create new content record
        content = Content(
            title=title,
            content_type=content_type,
            description=content_info.get('description', ''),
            genres=json.dumps(content_info.get('genres', [])),
            release_date=content_info.get('release_year', ''),
            author=content_info.get('creator', '') if content_type == 'book' else None,
            director=content_info.get('creator', '') if content_type == 'movie' else None
        )
        
        # Add TMDb data if available
        if tmdb_data:
            content.tmdb_id = tmdb_data.get('id')
            content.poster_url = tmdb_data.get('poster_path')
            content.rating = tmdb_data.get('vote_average')
            if tmdb_data.get('overview'):
                content.description = tmdb_data.get('overview')
        
        db.session.add(content)
        db.session.commit()
        
        return content
    
    def generate_recommendation_reasoning(self, content, preferences, search_result):
        """Generate explanation for why this content was recommended"""
        reasoning_prompt = f"""
        Generate a brief explanation for why this content was recommended to a user:
        
        Content: {content.title} ({content.content_type})
        Description: {content.description[:200]}
        Genres: {content.genres}
        
        User preferences:
        - Preferred genres: {preferences.get('preferred_genres', [])}
        - Analysis: {preferences.get('analysis', '')}
        
        Source context: {search_result.get('content', '')[:300]}
        
        Provide a 1-2 sentence explanation focusing on why this matches their preferences.
        """
        
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=reasoning_prompt
            )
            return response.text if response.text else "Recommended based on your interests"
        except Exception as e:
            logging.error(f"Error generating reasoning: {e}")
            return "Recommended based on your interests"
    
    def calculate_confidence_score(self, content, preferences):
        """Calculate confidence score for recommendation"""
        score = 0.5  # Base score
        
        try:
            content_genres = json.loads(content.genres) if content.genres else []
            preferred_genres = preferences.get('preferred_genres', [])
            
            # Genre matching
            genre_matches = len(set(content_genres) & set(preferred_genres))
            if preferred_genres:
                genre_score = genre_matches / len(preferred_genres)
                score += genre_score * 0.3
            
            # Content type preference
            preferred_types = preferences.get('content_types', [])
            if content.content_type in preferred_types:
                score += 0.1
            
            # Rating boost
            if content.rating and content.rating >= 7.0:
                score += 0.1
            
        except Exception as e:
            logging.error(f"Error calculating confidence: {e}")
        
        return min(1.0, max(0.1, score))
    
    def continuous_discovery(self, user):
        """Background task for continuous content discovery"""
        try:
            # Check if AI service is available
            if not self.client:
                logging.warning("AI service unavailable, creating sample recommendations")
                return self.create_fallback_recommendations(user)
            
            preferences = self.analyze_user_preferences(user)
            
            # Generate search queries based on preferences
            search_queries = self.generate_search_queries(preferences)
            
            all_recommendations = []
            
            for i, query in enumerate(search_queries[:2]):  # Limit to 2 queries to avoid timeouts
                try:
                    logging.info(f"Processing discovery query {i+1}/2: {query}")
                    recommendations = self.search_and_analyze_content(query, user)
                    all_recommendations.extend(recommendations)
                    
                    # Add delay between queries to avoid rate limiting
                    import time
                    time.sleep(1)
                    
                except Exception as e:
                    logging.error(f"Error in continuous discovery for query '{query}': {e}")
                    continue  # Continue with next query instead of failing entirely
            
            return all_recommendations
            
        except Exception as e:
            logging.error(f"Fatal error in continuous discovery: {e}")
            return self.create_fallback_recommendations(user)
    
    def create_fallback_recommendations(self, user):
        """Create basic recommendations when AI service is unavailable"""
        fallback_recommendations = []
        
        try:
            # Get user's preferred genres
            preferred_genres = []
            if user.preferred_genres:
                try:
                    preferred_genres = json.loads(user.preferred_genres)
                except:
                    preferred_genres = ['Action', 'Drama', 'Comedy']
            else:
                preferred_genres = ['Action', 'Drama', 'Comedy']
            
            # Create sample content recommendations based on popular titles
            sample_content = [
                {
                    'title': 'The Dark Knight',
                    'content_type': 'movie',
                    'description': 'A gripping superhero thriller with exceptional performances.',
                    'genres': ['Action', 'Crime', 'Drama'],
                    'release_year': '2008'
                },
                {
                    'title': 'Breaking Bad',
                    'content_type': 'tv_show', 
                    'description': 'A chemistry teacher becomes a drug kingpin.',
                    'genres': ['Crime', 'Drama', 'Thriller'],
                    'release_year': '2008'
                },
                {
                    'title': 'Dune',
                    'content_type': 'book',
                    'description': 'Epic science fiction novel about politics and power.',
                    'genres': ['Science Fiction', 'Adventure'],
                    'release_year': '1965'
                }
            ]
            
            for item in sample_content[:2]:  # Only create 2 fallback recommendations
                # Check if this matches user preferences
                item_genres = item['genres']
                if any(genre in preferred_genres for genre in item_genres):
                    
                    # Create or get content
                    content = Content.query.filter_by(
                        title=item['title'],
                        content_type=item['content_type']
                    ).first()
                    
                    if not content:
                        content = Content(
                            title=item['title'],
                            content_type=item['content_type'],
                            description=item['description'],
                            genres=json.dumps(item['genres']),
                            release_date=item['release_year']
                        )
                        db.session.add(content)
                        db.session.commit()
                    
                    # Create recommendation
                    recommendation = Recommendation(
                        user_id=user.id,
                        content_id=content.id,
                        confidence_score=0.7,
                        reasoning="Recommended based on your genre preferences while AI service is temporarily unavailable.",
                        source_urls=json.dumps([])
                    )
                    
                    db.session.add(recommendation)
                    fallback_recommendations.append(recommendation)
            
            db.session.commit()
            
        except Exception as e:
            logging.error(f"Error creating fallback recommendations: {e}")
        
        return fallback_recommendations
    
    def generate_search_queries(self, preferences):
        """Generate search queries based on user preferences"""
        queries = []
        
        preferred_genres = preferences.get('preferred_genres', [])
        if preferred_genres:
            # Genre-based queries
            for genre in preferred_genres[:3]:
                queries.append(f"best {genre} movies 2024")
                queries.append(f"recommended {genre} TV shows")
        
        # General discovery queries
        queries.extend([
            "new movie releases 2024 reviews",
            "best TV shows streaming now",
            "must read books 2024",
            "hidden gem movies recommendations",
            "critically acclaimed series"
        ])
        
        return queries[:5]  # Return top 5 queries
