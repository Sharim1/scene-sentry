"""
Gossip Scraper Agent for entertainment news

This agent scrapes entertainment news and gossip from various sources,
extracts relevant information, and matches it to user-tracked content.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from tavily import TavilyClient

from app.database import db_session
from app.models import Gossip, Content
from app.models.gossip import GossipTag

logger = logging.getLogger(__name__)


class GossipScraperAgent:
    """
    AI agent that scrapes and curates entertainment gossip and news
    """
    
    # Entertainment news sources
    SOURCES = [
        "variety.com",
        "deadline.com",
        "hollywoodreporter.com",
        "ew.com",
        "tvline.com",
        "screenrant.com",
        "collider.com",
        "ign.com/articles",
        "denofgeek.com"
    ]
    
    # Keywords to search for entertainment news
    KEYWORDS = [
        "casting news",
        "renewal cancelled",
        "season premiere",
        "production update",
        "exclusive interview",
        "behind the scenes",
        "adaptation announced",
        "release date",
        "trailer released"
    ]
    
    def __init__(self):
        self.llm = self._initialize_llm()
        self.tavily = self._initialize_tavily()
        
    def _initialize_llm(self):
        """Initialize the Google Gemini LLM"""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found, gossip analysis will be limited")
            return None
        
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash-exp",
            google_api_key=api_key,
            temperature=0.3,  # Lower temperature for more factual extraction
            max_output_tokens=2048,
        )
    
    def _initialize_tavily(self):
        """Initialize Tavily search client"""
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logger.warning("TAVILY_API_KEY not found, gossip scraping will be limited")
            return None
        
        return TavilyClient(api_key=api_key)
    
    async def scrape_gossip(self, tracked_titles: List[str] = None) -> List[Dict[str, Any]]:
        """
        Scrape latest entertainment gossip
        
        Args:
            tracked_titles: List of content titles the user is tracking (for personalization)
            
        Returns:
            List of gossip items created
        """
        logger.info("Starting gossip scraping...")
        
        if not self.tavily:
            logger.warning("Tavily not available, skipping gossip scrape")
            return []
        
        gossip_items = []
        
        # Build search queries
        queries = self._build_search_queries(tracked_titles)
        
        for query in queries[:5]:  # Limit to 5 queries
            try:
                results = await self._search_news(query)
                
                for result in results[:3]:  # Top 3 results per query
                    gossip = await self._process_news_result(result, tracked_titles)
                    if gossip:
                        gossip_items.append(gossip)
                        
            except Exception as e:
                logger.error(f"Error processing query '{query}': {e}")
                continue
        
        logger.info(f"Gossip scraping completed: {len(gossip_items)} items")
        return gossip_items
    
    def _build_search_queries(self, tracked_titles: List[str] = None) -> List[str]:
        """Build search queries for gossip"""
        queries = []
        
        # General entertainment news queries
        queries.extend([
            "entertainment news today TV shows movies",
            "casting news 2024 TV series",
            "show renewal cancellation news",
            "book to TV adaptation announcements",
            "streaming series exclusive news"
        ])
        
        # Add queries for tracked titles
        if tracked_titles:
            for title in tracked_titles[:5]:
                queries.append(f"{title} news cast production 2024")
        
        return queries
    
    async def _search_news(self, query: str) -> List[Dict[str, Any]]:
        """Search for news using Tavily"""
        try:
            response = self.tavily.search(
                query=query,
                max_results=5,
                search_depth="advanced",
                include_domains=self.SOURCES
            )
            return response.get("results", [])
        except Exception as e:
            logger.error(f"Tavily search error: {e}")
            return []
    
    async def _process_news_result(
        self, 
        result: Dict[str, Any],
        tracked_titles: List[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Process a single news result into gossip"""
        try:
            url = result.get("url", "")
            title = result.get("title", "")
            content = result.get("content", "")
            
            if not title or not content:
                return None
            
            # Check if already exists
            with db_session() as db:
                existing = db.query(Gossip).filter(
                    Gossip.source_url == url
                ).first()
                
                if existing:
                    return None
            
            # Extract source name from URL
            source_name = self._extract_source_name(url)
            
            # Use LLM to analyze and structure the gossip
            if self.llm:
                analysis = await self._analyze_gossip(title, content, tracked_titles)
            else:
                analysis = self._basic_analysis(title, content)
            
            # Create gossip record
            with db_session() as db:
                gossip = Gossip(
                    title=analysis.get("title", title),
                    content=content[:2000],  # Limit content length
                    summary=analysis.get("summary"),
                    source_url=url,
                    source_name=source_name,
                    image_url=result.get("image_url"),
                    tag=self._map_tag(analysis.get("tag", "rumor")),
                    confidence_score=analysis.get("confidence", 0.5),
                    sentiment=analysis.get("sentiment", "neutral"),
                    keywords=json.dumps(analysis.get("keywords", [])),
                    mentioned_titles=json.dumps(analysis.get("mentioned_titles", [])),
                    is_featured=analysis.get("is_featured", False)
                )
                
                # Try to match to existing content
                if analysis.get("mentioned_titles"):
                    for mentioned in analysis["mentioned_titles"]:
                        content_match = db.query(Content).filter(
                            Content.title.ilike(f"%{mentioned}%")
                        ).first()
                        
                        if content_match:
                            gossip.related_content_id = content_match.id
                            break
                
                db.add(gossip)
                
                return {
                    "id": gossip.id,
                    "title": gossip.title,
                    "source": source_name,
                    "tag": gossip.tag.value if gossip.tag else "rumor"
                }
                
        except Exception as e:
            logger.error(f"Error processing news result: {e}")
            return None
    
    def _extract_source_name(self, url: str) -> str:
        """Extract source name from URL"""
        source_map = {
            "variety.com": "Variety",
            "deadline.com": "Deadline",
            "hollywoodreporter.com": "Hollywood Reporter",
            "ew.com": "Entertainment Weekly",
            "tvline.com": "TVLine",
            "screenrant.com": "Screen Rant",
            "collider.com": "Collider",
            "ign.com": "IGN",
            "denofgeek.com": "Den of Geek"
        }
        
        for domain, name in source_map.items():
            if domain in url:
                return name
        
        return "Unknown Source"
    
    async def _analyze_gossip(
        self,
        title: str,
        content: str,
        tracked_titles: List[str] = None
    ) -> Dict[str, Any]:
        """Use LLM to analyze and structure gossip"""
        prompt = f"""
        Analyze this entertainment news article and extract structured information:
        
        Title: {title}
        Content: {content[:1500]}
        
        User is tracking these shows/movies: {tracked_titles[:10] if tracked_titles else "None specified"}
        
        Please extract:
        1. A compelling headline (max 100 chars)
        2. A brief summary (2-3 sentences)
        3. Category tag: one of [exclusive, casting, production, rumor, renewal, cancellation, release, adaptation, behind_scenes, interview, review, trending]
        4. Sentiment: positive, negative, or neutral
        5. Confidence score (0-1) - how reliable does this news seem?
        6. Keywords (up to 5)
        7. Mentioned TV shows/movies/books (titles only)
        8. Is this featured-worthy (major breaking news)?
        
        Respond in JSON format:
        {{
            "title": "...",
            "summary": "...",
            "tag": "...",
            "sentiment": "...",
            "confidence": 0.8,
            "keywords": ["...", "..."],
            "mentioned_titles": ["...", "..."],
            "is_featured": false
        }}
        """
        
        try:
            messages = [HumanMessage(content=prompt)]
            response = await self.llm.ainvoke(messages)
            
            content = response.content
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
            else:
                json_str = content.strip()
            
            return json.loads(json_str)
            
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return self._basic_analysis(title, content)
    
    def _basic_analysis(self, title: str, content: str) -> Dict[str, Any]:
        """Basic analysis without LLM"""
        # Simple keyword-based classification
        tag = "rumor"
        
        lower_content = (title + " " + content).lower()
        
        if any(word in lower_content for word in ["cast", "casting", "star"]):
            tag = "casting"
        elif any(word in lower_content for word in ["renew", "season", "pickup"]):
            tag = "renewal"
        elif any(word in lower_content for word in ["cancel", "ended", "final"]):
            tag = "cancellation"
        elif any(word in lower_content for word in ["production", "filming", "set"]):
            tag = "production"
        elif any(word in lower_content for word in ["exclusive", "first look"]):
            tag = "exclusive"
        elif any(word in lower_content for word in ["release", "premiere", "trailer"]):
            tag = "release"
        
        return {
            "title": title[:100],
            "summary": content[:200] + "...",
            "tag": tag,
            "sentiment": "neutral",
            "confidence": 0.5,
            "keywords": [],
            "mentioned_titles": [],
            "is_featured": False
        }
    
    def _map_tag(self, tag_str: str) -> GossipTag:
        """Map string tag to GossipTag enum"""
        tag_map = {
            "exclusive": GossipTag.EXCLUSIVE,
            "casting": GossipTag.CASTING,
            "production": GossipTag.PRODUCTION,
            "rumor": GossipTag.RUMOR,
            "renewal": GossipTag.RENEWAL,
            "cancellation": GossipTag.CANCELLATION,
            "release": GossipTag.RELEASE,
            "adaptation": GossipTag.ADAPTATION,
            "behind_scenes": GossipTag.BEHIND_SCENES,
            "interview": GossipTag.INTERVIEW,
            "review": GossipTag.REVIEW,
            "trending": GossipTag.TRENDING
        }
        
        return tag_map.get(tag_str.lower(), GossipTag.RUMOR)
    
    async def scrape_for_content(self, content: Content) -> List[Dict[str, Any]]:
        """Scrape gossip specifically for a content item"""
        if not self.tavily:
            return []
        
        query = f"{content.title} news {datetime.now().year}"
        
        try:
            results = await self._search_news(query)
            
            gossip_items = []
            for result in results[:5]:
                gossip = await self._process_news_result(result, [content.title])
                if gossip:
                    gossip_items.append(gossip)
            
            return gossip_items
            
        except Exception as e:
            logger.error(f"Error scraping for content '{content.title}': {e}")
            return []


# Global instance
gossip_agent = GossipScraperAgent()

