"""
Recommendation and search log models
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    """Get current UTC time (timezone-aware)"""
    return datetime.now(UTC)


class Recommendation(Base):
    """AI-generated recommendation for a user"""

    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True)

    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=False, index=True)

    # Recommendation details
    confidence_score = Column(Float, default=0.5)  # 0-1 confidence
    reasoning = Column(Text, nullable=True)  # Why this was recommended
    source_urls = Column(Text, nullable=True)  # JSON array of source URLs

    # Agent info
    agent_type = Column(String(50), default="discovery")  # 'discovery', 'gossip', 'trending'

    # User interaction
    viewed = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    saved_to_library = Column(Boolean, default=False)

    # Timestamps (timezone-aware)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    viewed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="recommendations")
    content = relationship("Content", back_populates="recommendations")

    def __repr__(self):
        return f"<Recommendation {self.content_id} for user {self.user_id}>"


class SearchLog(Base):
    """Log of AI searches performed"""

    __tablename__ = "search_logs"

    id = Column(Integer, primary_key=True)

    # Search info
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    query = Column(String(500), nullable=False)
    api_used = Column(String(20), nullable=False)  # 'tavily', 'brightdata', 'tmdb'

    # Results
    results_count = Column(Integer, default=0)
    execution_time = Column(Float, nullable=True)  # In seconds

    # Timestamps (timezone-aware)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    def __repr__(self):
        return f"<SearchLog '{self.query[:30]}...'>"
