"""
Reminder model for notifications
"""
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    """Get current UTC time (timezone-aware)"""
    return datetime.now(timezone.utc)


class ReminderType(str, PyEnum):
    """Types of reminders"""
    WATCH = "watch"
    READ = "read"
    NEXT_EPISODE = "next_episode"
    PREMIERE = "premiere"
    FINALE = "finale"
    RELEASE = "release"


class Reminder(Base):
    """Reminder for upcoming content"""
    __tablename__ = "reminders"
    
    id = Column(Integer, primary_key=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    library_item_id = Column(Integer, ForeignKey("library_items.id"), nullable=True, index=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=True, index=True)
    
    # Reminder details
    reminder_type = Column(Enum(ReminderType, native_enum=False), nullable=False)
    scheduled_time = Column(DateTime(timezone=True), nullable=False, index=True)
    message = Column(Text, nullable=True)
    platform = Column(String(50), nullable=True)
    quality = Column(String(50), nullable=True)
    
    # Status
    sent = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)
    
    # Timestamps (timezone-aware)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="reminders")
    library_item = relationship("LibraryItem", back_populates="reminders")
    content = relationship("Content")
    
    def __repr__(self):
        return f"<Reminder {self.reminder_type} at {self.scheduled_time}>"

