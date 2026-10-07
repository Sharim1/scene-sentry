"""
Gossip model for entertainment news and rumors
"""

from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    """Get current UTC time (timezone-aware)"""
    return datetime.now(UTC)


class GossipTag(str, PyEnum):
    """Tags for gossip/news items"""

    EXCLUSIVE = "exclusive"
    CASTING = "casting"
    PRODUCTION = "production"
    RUMOR = "rumor"
    RENEWAL = "renewal"
    CANCELLATION = "cancellation"
    RELEASE = "release"
    ADAPTATION = "adaptation"
    BEHIND_SCENES = "behind_scenes"
    INTERVIEW = "interview"
    REVIEW = "review"
    TRENDING = "trending"


class Gossip(Base):
    """Entertainment news and gossip item"""

    __tablename__ = "gossip"

    id = Column(Integer, primary_key=True)

    # Content
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)  # Deprecated – no longer written
    preview_text = Column(Text, nullable=True)  # Short snippet (~200 chars)

    # Source info
    source_url = Column(String(500), nullable=False)
    source_name = Column(String(100), nullable=False)  # 'Variety', 'Deadline', etc.
    source_author = Column(String(200), nullable=True)

    # Media
    image_url = Column(String(500), nullable=True)

    # Classification
    tag = Column(Enum(GossipTag, native_enum=False), default=GossipTag.RUMOR)

    # AI analysis
    confidence_score = Column(Float, default=0.5)  # How confident AI is about accuracy
    sentiment = Column(String(20), nullable=True)  # 'positive', 'negative', 'neutral'
    keywords = Column(Text, nullable=True)  # JSON array of extracted keywords

    # Related content
    related_content_id = Column(Integer, ForeignKey("content.id"), nullable=True, index=True)
    mentioned_titles = Column(Text, nullable=True)  # JSON array of mentioned show/movie titles

    # Engagement (for future features)
    view_count = Column(Integer, default=0)
    share_count = Column(Integer, default=0)

    # Status
    is_verified = Column(Boolean, default=False)
    is_featured = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # Timestamps (using timezone-aware UTC)
    published_at = Column(DateTime(timezone=True), nullable=True)  # Original publish date
    scraped_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    related_content = relationship("Content", back_populates="gossip_items")

    def __repr__(self):
        return f"<Gossip '{self.title[:50]}...'>"

    @property
    def time_ago(self) -> str:
        """Get human-readable time ago string"""
        if not self.scraped_at:
            return "Unknown"

        now = datetime.now(UTC)
        scraped = self.scraped_at

        # Handle offset-naive datetimes from existing database records
        if scraped.tzinfo is None:
            scraped = scraped.replace(tzinfo=UTC)

        diff = now - scraped

        if diff.days > 0:
            return f"{diff.days}d ago"
        elif diff.seconds >= 3600:
            hours = diff.seconds // 3600
            return f"{hours}h ago"
        elif diff.seconds >= 60:
            minutes = diff.seconds // 60
            return f"{minutes}m ago"
        else:
            return "Just now"
