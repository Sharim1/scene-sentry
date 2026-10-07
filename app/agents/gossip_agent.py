"""
Gossip Scraper Agent for entertainment news

Simplified agent that scrapes headlines and preview text from entertainment
news sources via Tavily. No LLM analysis – stores only title, source URL,
image, and a short preview snippet. "Read More" links redirect to the
original article.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

try:
    from tavily import TavilyClient

    TAVILY_AVAILABLE = True
except ImportError:
    logger.warning("Tavily not available")
    TavilyClient = None
    TAVILY_AVAILABLE = False

from app.models import Content, Gossip
from app.models.gossip import GossipTag

if TYPE_CHECKING:
    from app.agents import SessionFactory


class GossipScraperAgent:
    """Scrapes and stores entertainment gossip headlines with preview text."""

    SOURCES = [
        "variety.com",
        "deadline.com",
        "hollywoodreporter.com",
        "ew.com",
        "tvline.com",
        "screenrant.com",
        "collider.com",
        "ign.com/articles",
        "denofgeek.com",
    ]

    def __init__(self, session_factory: SessionFactory | None = None):
        from app.database import db_session

        self._session_factory = session_factory or db_session
        self.tavily = self._initialize_tavily()

    def _initialize_tavily(self):
        if not TAVILY_AVAILABLE or TavilyClient is None:
            return None
        from app.config import settings

        api_key = settings.tavily_api_key
        if not api_key:
            logger.warning("TAVILY_API_KEY not found, gossip scraping disabled")
            return None
        try:
            return TavilyClient(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialise Tavily: {e}")
            return None

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Reject private/internal URLs to prevent SSRF."""
        import ipaddress
        import socket

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return False
        except ValueError:
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                for _, _, _, _, sockaddr in resolved:
                    addr = ipaddress.ip_address(sockaddr[0])
                    if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                        return False
            except socket.gaierror:
                return False
        return True

    async def _fetch_og_image(self, url: str) -> str | None:
        try:
            if not self._is_safe_url(url):
                return None
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code != 200:
                    return None
                html = resp.text
                patterns = [
                    r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                    r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                    r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
                ]
                for pat in patterns:
                    match = re.search(pat, html, re.IGNORECASE)
                    if match and match.group(1).startswith("http"):
                        return match.group(1)
        except Exception:
            pass
        return None

    def _validate_article_url(self, url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        path = parsed.path.strip("/")
        if not path:
            return False
        segments = [s for s in path.split("/") if s]
        for seg in segments:
            if re.match(r"^\d{5,}$", seg):
                return True
            if seg.count("-") >= 2 and len(seg) > 15:
                return True
            if len(seg) > 20 and re.match(r"^[a-z0-9-]+$", seg, re.IGNORECASE):
                return True
        return False

    async def scrape_gossip(self, tracked_titles: list[str] = None) -> list[dict[str, Any]]:
        logger.info("Starting gossip scraping...")
        if not self.tavily:
            logger.warning("Tavily not available, skipping gossip scrape")
            return []

        gossip_items: list[dict[str, Any]] = []
        queries = self._build_search_queries(tracked_titles)

        for query in queries[:5]:
            try:
                results = self._search_news(query)
                for result in results[:3]:
                    gossip = await self._process_news_result(result, tracked_titles)
                    if gossip:
                        gossip_items.append(gossip)
            except Exception as e:
                logger.error(f"Error processing query '{query}': {e}")
        logger.info(f"Gossip scraping completed: {len(gossip_items)} items")
        return gossip_items

    def _build_search_queries(self, tracked_titles: list[str] = None) -> list[str]:
        current_year = datetime.now().year
        queries = [
            f"exclusive casting news {current_year} TV series announced",
            f"TV show renewed cancelled {current_year}",
            f"new movie trailer release date {current_year}",
            f"streaming series premiere announced {current_year}",
            f"actor joins cast movie {current_year}",
        ]
        if tracked_titles:
            for title in tracked_titles[:5]:
                queries.append(f'"{title}" news cast production {current_year}')
        return queries

    def _search_news(self, query: str) -> list[dict[str, Any]]:
        try:
            resp = self.tavily.search(
                query=query,
                max_results=5,
                search_depth="advanced",
                include_domains=self.SOURCES,
                include_images=True,
                include_raw_content=False,
            )
            return resp.get("results", [])
        except Exception as e:
            logger.error(f"Tavily search error: {e}")
            return []

    async def _process_news_result(
        self, result: dict[str, Any], tracked_titles: list[str] = None
    ) -> dict[str, Any] | None:
        try:
            url = result.get("url", "")
            title = result.get("title", "")
            content = result.get("content", "")

            if not title or not url:
                return None
            if not self._validate_article_url(url):
                return None

            with self._session_factory() as db:
                if db.query(Gossip).filter(Gossip.source_url == url).first():
                    return None

            source_name = self._extract_source_name(url)
            image_url = None
            images = result.get("images", [])
            if images and isinstance(images, list):
                image_url = images[0] if isinstance(images[0], str) else images[0].get("url")
            if not image_url:
                image_url = result.get("image_url")
            if not image_url:
                image_url = await self._fetch_og_image(url)

            preview = (content[:200].rsplit(" ", 1)[0] + "...") if len(content) > 200 else content
            tag = self._classify_tag(title, content)

            with self._session_factory() as db:
                gossip = Gossip(
                    title=title[:200],
                    content=preview,
                    preview_text=preview,
                    source_url=url,
                    source_name=source_name,
                    image_url=image_url,
                    tag=tag,
                    confidence_score=0.5,
                )

                if tracked_titles:
                    for t in tracked_titles:
                        match = db.query(Content).filter(Content.title.ilike(f"%{t}%")).first()
                        if match:
                            gossip.related_content_id = match.id
                            break

                db.add(gossip)
                return {
                    "id": gossip.id,
                    "title": gossip.title,
                    "source": source_name,
                    "tag": gossip.tag.value if gossip.tag else "rumor",
                    "image_url": image_url,
                }
        except Exception as e:
            logger.error(f"Error processing news result: {e}")
            return None

    def _extract_source_name(self, url: str) -> str:
        source_map = {
            "variety.com": "Variety",
            "deadline.com": "Deadline",
            "hollywoodreporter.com": "Hollywood Reporter",
            "ew.com": "Entertainment Weekly",
            "tvline.com": "TVLine",
            "screenrant.com": "Screen Rant",
            "collider.com": "Collider",
            "ign.com": "IGN",
            "denofgeek.com": "Den of Geek",
        }
        for domain, name in source_map.items():
            if domain in url:
                return name
        return "Unknown Source"

    def _classify_tag(self, title: str, content: str) -> GossipTag:
        text = (title + " " + content).lower()
        if any(w in text for w in ["cast", "casting", "star", "join"]):
            return GossipTag.CASTING
        if any(w in text for w in ["renew", "season", "pickup", "order"]):
            return GossipTag.RENEWAL
        if any(w in text for w in ["cancel", "ended", "final", "axed"]):
            return GossipTag.CANCELLATION
        if any(w in text for w in ["production", "filming", "set", "wrap"]):
            return GossipTag.PRODUCTION
        if any(w in text for w in ["exclusive", "first look", "sneak peek"]):
            return GossipTag.EXCLUSIVE
        if any(w in text for w in ["release", "premiere", "trailer", "teaser"]):
            return GossipTag.RELEASE
        if any(w in text for w in ["adapt", "based on", "book"]):
            return GossipTag.ADAPTATION
        return GossipTag.RUMOR


_gossip_agent = None


def get_gossip_agent(session_factory: SessionFactory | None = None) -> GossipScraperAgent:
    global _gossip_agent
    if session_factory is not None:
        return GossipScraperAgent(session_factory=session_factory)
    if _gossip_agent is None:
        try:
            _gossip_agent = GossipScraperAgent()
            logger.info("GossipScraperAgent initialized")
        except Exception as e:
            logger.error(f"Failed to create GossipScraperAgent: {e}")
            _gossip_agent = GossipScraperAgent.__new__(GossipScraperAgent)
            _gossip_agent.tavily = None
            _gossip_agent._session_factory = None
    return _gossip_agent
