"""
Library item model for user's tracked content
"""
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    """Get current UTC time (timezone-aware)"""
    return datetime.now(timezone.utc)


class WatchStatus(str, PyEnum):
    """Status options for library items"""
    WATCHING = "watching"
    PLANNED = "planned"
    COMPLETED = "completed"
    DROPPED = "dropped"
    MAYBE = "maybe"


class LibraryItem(Base):
    """User's library item - tracks what they're watching/reading"""
    __tablename__ = "library_items"
    
    id = Column(Integer, primary_key=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=False, index=True)
    
    # Status
    status = Column(
        Enum(WatchStatus),
        nullable=False,
        default=WatchStatus.PLANNED
    )
    
    # Progress tracking
    progress = Column(Integer, default=0)  # Episodes watched / pages read
    current_season = Column(Integer, nullable=True)
    current_episode = Column(Integer, nullable=True)
    
    # User rating and notes
    rating = Column(Integer, nullable=True)  # 1-5 stars
    notes = Column(Text, nullable=True)
    
    # Weekly release tracking
    weekly_release = Column(Boolean, default=False)
    next_episode_date = Column(DateTime, nullable=True)
    
    # Priority/order
    priority = Column(Integer, default=0)  # For ordering watchlist
    
    # Timestamps (timezone-aware)
    added_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="library_items")
    content = relationship("Content", back_populates="library_items")
    reminders = relationship("Reminder", back_populates="library_item", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<LibraryItem {self.content_id} - {self.status}>"

