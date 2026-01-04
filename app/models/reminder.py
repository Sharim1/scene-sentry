"""
Reminder model for notifications
"""
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.database import Base


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
    library_item_id = Column(Integer, ForeignKey("library_items.id"), nullable=False, index=True)
    
    # Reminder details
    reminder_type = Column(Enum(ReminderType), nullable=False)
    scheduled_time = Column(DateTime, nullable=False, index=True)
    message = Column(Text, nullable=True)
    
    # Status
    sent = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="reminders")
    library_item = relationship("LibraryItem", back_populates="reminders")
    
    def __repr__(self):
        return f"<Reminder {self.reminder_type} at {self.scheduled_time}>"

