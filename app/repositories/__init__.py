"""
Repository layer - thin DB access wrappers
"""

from app.repositories.content_repo import ContentRepository
from app.repositories.gossip_repo import GossipRepository
from app.repositories.library_repo import LibraryRepository
from app.repositories.ranking_repo import RankingRepository
from app.repositories.reminder_repo import ReminderRepository

__all__ = [
    "ContentRepository",
    "GossipRepository",
    "ReminderRepository",
    "LibraryRepository",
    "RankingRepository",
]
