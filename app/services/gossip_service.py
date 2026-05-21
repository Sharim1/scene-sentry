"""
Gossip service — orchestrates scraping via the Gossip agent.

Read queries (feed, latest, tag counts) belong on GossipRepository directly;
this service exists only for operations that coordinate multiple subsystems.
"""

import logging

logger = logging.getLogger(__name__)


class GossipService:
    """Thin orchestrator for gossip-related side-effecting operations."""

    async def scrape_latest(self, tracked_titles: list[str]) -> list[dict]:
        """Run the Tavily scraper agent for the given tracked titles."""
        from app.agents.gossip_agent import get_gossip_agent

        agent = get_gossip_agent()
        return await agent.scrape_gossip(tracked_titles[:10])
