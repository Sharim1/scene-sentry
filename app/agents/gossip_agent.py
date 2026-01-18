"""
Gossip Scraper Agent for entertainment news

This agent scrapes entertainment news and gossip from various sources,
extracts relevant information, and matches it to user-tracked content.
"""

import json
import logging
import re
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Try to import trafilatura for content cleaning
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    logger.warning("trafilatura not available, content cleaning will be limited")
    TRAFILATURA_AVAILABLE = False

# Try to import LLM - may fail due to protobuf issues
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    LLM_AVAILABLE = True
except ImportError as e:
    logger.warning(f"LLM imports failed: {e}. Will use basic analysis.")
    ChatGoogleGenerativeAI = None
    HumanMessage = None
    LLM_AVAILABLE = False

# Try to import Tavily
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Tavily import failed: {e}")
    TavilyClient = None
    TAVILY_AVAILABLE = False

from app.database import db_session
from app.models import Gossip, Content
from app.models.gossip import GossipTag


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
        if not LLM_AVAILABLE or ChatGoogleGenerativeAI is None:
            logger.warning("LLM not available due to import errors, gossip analysis will be limited")
            return None
            
        from app.config import settings
        api_key = settings.gemini_api_key
        if not api_key:
            logger.warning("GEMINI_API_KEY not found, gossip analysis will be limited")
            return None
        
        try:
            return ChatGoogleGenerativeAI(
                model="gemini-2.0-flash-exp",
                google_api_key=api_key,
                temperature=0.3,  # Lower temperature for more factual extraction
                max_output_tokens=2048,
            )
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            return None
    
    def _initialize_tavily(self):
        """Initialize Tavily search client"""
        if not TAVILY_AVAILABLE or TavilyClient is None:
            logger.warning("Tavily not available due to import errors")
            return None
            
        from app.config import settings
        api_key = settings.tavily_api_key
        if not api_key:
            logger.warning("TAVILY_API_KEY not found, gossip scraping will be limited")
            return None
        
        try:
            return TavilyClient(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize Tavily: {e}")
            return None
    
    async def _fetch_og_image(self, url: str) -> Optional[str]:
        """Fetch og:image meta tag from a URL"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, follow_redirects=True)
                if response.status_code != 200:
                    return None
                
                html = response.text
                
                # Try to find og:image
                og_patterns = [
                    r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                    r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                    r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
                ]
                
                for pattern in og_patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        image_url = match.group(1)
                        # Validate URL
                        if image_url.startswith('http'):
                            return image_url
                
        except Exception as e:
            logger.debug(f"Failed to fetch og:image from {url}: {e}")
        
        return None
    
    def _clean_content(self, content: str, url: str = None) -> str:
        """Clean and extract main content from raw HTML or text"""
        if not content:
            return ""
        
        # If content is HTML and trafilatura is available, use it
        if TRAFILATURA_AVAILABLE and ('<html' in content.lower() or '<body' in content.lower()):
            try:
                cleaned = trafilatura.extract(content)
                if cleaned:
                    return cleaned
            except Exception as e:
                logger.debug(f"trafilatura extraction failed: {e}")
        
        # Basic cleaning
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', content)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove common boilerplate phrases
        boilerplate = [
            r'Sign up for our newsletter',
            r'Subscribe to .+? newsletter',
            r'Get the latest news',
            r'Follow us on .+',
            r'Share this article',
            r'READ MORE:',
            r'RELATED:',
            r'SEE ALSO:',
        ]
        for pattern in boilerplate:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        return text.strip()
    
    def _validate_article_url(self, url: str) -> bool:
        """Check if URL is a valid article URL (not just a domain)"""
        if not url:
            return False
        
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # A valid article URL should have a path with some content
        if not path:
            return False
        
        # Should have more than just one segment
        segments = path.split('/')
        if len(segments) < 1:
            return False
        
        # Should not be a category or section page (usually shorter paths)
        if len(path) < 10:
            return False
        
        return True
    
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
                include_domains=self.SOURCES,
                include_images=True,  # Request images in results
                include_raw_content=False  # We'll fetch content separately if needed
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
            
            # Validate URL is an actual article
            if not self._validate_article_url(url):
                logger.debug(f"Skipping non-article URL: {url}")
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
            
            # Get image - try multiple sources
            image_url = None
            
            # 1. Try images array from Tavily
            images = result.get("images", [])
            if images and isinstance(images, list) and len(images) > 0:
                image_url = images[0] if isinstance(images[0], str) else images[0].get("url")
            
            # 2. Try image_url field directly
            if not image_url:
                image_url = result.get("image_url")
            
            # 3. Fetch og:image from the article page
            if not image_url:
                image_url = await self._fetch_og_image(url)
            
            # Clean content before processing
            cleaned_content = self._clean_content(content, url)
            
            # Use LLM to analyze and structure the gossip
            if self.llm:
                analysis = await self._analyze_gossip(title, cleaned_content, tracked_titles)
            else:
                analysis = self._basic_analysis(title, cleaned_content)
            
            # Create gossip record
            with db_session() as db:
                gossip = Gossip(
                    title=analysis.get("title", title)[:200],
                    content=cleaned_content[:2000],  # Limit content length
                    summary=analysis.get("summary"),
                    source_url=url,  # Use the full article URL
                    source_name=source_name,
                    image_url=image_url,
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
                    "tag": gossip.tag.value if gossip.tag else "rumor",
                    "image_url": image_url
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
        # Truncate content for token efficiency
        truncated_content = content[:1200] if len(content) > 1200 else content
        
        prompt = f"""Analyze this entertainment news article and provide a structured summary.

Title: {title}

Content: {truncated_content}

{"User is tracking: " + ", ".join(tracked_titles[:5]) if tracked_titles else ""}

Provide a response in this exact JSON format:
{{
    "title": "A concise, compelling headline (max 100 characters)",
    "summary": "A human-friendly 2-3 sentence summary of the key news. Write it as if you're telling a friend about this story.",
    "tag": "one of: exclusive, casting, production, rumor, renewal, cancellation, release, adaptation, behind_scenes, interview, review, trending",
    "sentiment": "positive, negative, or neutral",
    "confidence": 0.8,
    "keywords": ["keyword1", "keyword2"],
    "mentioned_titles": ["Show Name", "Movie Name"],
    "is_featured": false
}}

Important:
- Write the summary in a natural, conversational tone
- Focus on the most newsworthy aspect
- Include specific names/titles when relevant
- Keep the headline punchy and engaging"""
        
        try:
            messages = [HumanMessage(content=prompt)]
            response = await self.llm.ainvoke(messages)
            
            response_content = response.content
            if "```json" in response_content:
                json_start = response_content.find("```json") + 7
                json_end = response_content.find("```", json_start)
                json_str = response_content[json_start:json_end].strip()
            elif "```" in response_content:
                json_start = response_content.find("```") + 3
                json_end = response_content.find("```", json_start)
                json_str = response_content[json_start:json_end].strip()
            else:
                json_str = response_content.strip()
            
            return json.loads(json_str)
            
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return self._basic_analysis(title, content)
    
    def _basic_analysis(self, title: str, content: str) -> Dict[str, Any]:
        """Basic analysis without LLM"""
        # Simple keyword-based classification
        tag = "rumor"
        
        lower_content = (title + " " + content).lower()
        
        if any(word in lower_content for word in ["cast", "casting", "star", "join"]):
            tag = "casting"
        elif any(word in lower_content for word in ["renew", "season", "pickup", "order"]):
            tag = "renewal"
        elif any(word in lower_content for word in ["cancel", "ended", "final", "axed"]):
            tag = "cancellation"
        elif any(word in lower_content for word in ["production", "filming", "set", "wrap"]):
            tag = "production"
        elif any(word in lower_content for word in ["exclusive", "first look", "sneak peek"]):
            tag = "exclusive"
        elif any(word in lower_content for word in ["release", "premiere", "trailer", "teaser"]):
            tag = "release"
        elif any(word in lower_content for word in ["adapt", "based on", "book"]):
            tag = "adaptation"
        
        # Create a basic summary from first sentences
        sentences = re.split(r'[.!?]+', content)
        summary = '. '.join(sentences[:2]).strip()
        if summary and not summary.endswith('.'):
            summary += '.'
        if len(summary) > 300:
            summary = summary[:297] + '...'
        
        return {
            "title": title[:100],
            "summary": summary or "Read the full article for details.",
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


# Lazy-loaded global instance
_gossip_agent = None

def get_gossip_agent():
    """Get or create the gossip agent instance (lazy loading)"""
    global _gossip_agent
    if _gossip_agent is None:
        try:
            _gossip_agent = GossipScraperAgent()
            logger.info("GossipScraperAgent initialized successfully")
        except Exception as e:
            logger.error(f"Failed to create GossipScraperAgent: {e}")
            # Return a minimal agent that can still work without LLM
            _gossip_agent = GossipScraperAgent.__new__(GossipScraperAgent)
            _gossip_agent.llm = None
            _gossip_agent.tavily = None
            # Try to initialize Tavily at least
            try:
                if TAVILY_AVAILABLE and TavilyClient:
                    from app.config import settings
                    if settings.tavily_api_key:
                        _gossip_agent.tavily = TavilyClient(api_key=settings.tavily_api_key)
                        logger.info("Tavily initialized in fallback mode")
            except Exception as tavily_error:
                logger.error(f"Failed to initialize Tavily in fallback: {tavily_error}")
    return _gossip_agent

# For backward compatibility - create a simple wrapper
class _GossipAgentProxy:
    def __getattr__(self, name):
        return getattr(get_gossip_agent(), name)

gossip_agent = _GossipAgentProxy()
