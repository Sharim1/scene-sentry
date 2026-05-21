"""
AI Agent System
"""

from collections.abc import Generator
from typing import Protocol


class SessionFactory(Protocol):
    """Callable that returns a context manager yielding a SQLAlchemy Session.

    The default implementation is ``app.database.db_session``.  Inject an
    alternative (e.g. a test fixture) to decouple agents from the real DB.
    """

    def __call__(self) -> Generator: ...


from app.agents.gossip_agent import get_gossip_agent
from app.agents.graph import ranking_graph

__all__ = ["SessionFactory", "ranking_graph", "get_gossip_agent"]
