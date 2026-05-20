"""
UserContentRank model for personalized content scoring
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    return datetime.now(UTC)


class UserContentRank(Base):
    """Stores per-user relevance scores produced by the re-ranking agent."""

    __tablename__ = "user_content_ranks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=False, index=True)
    rank_score = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=True)
    ranked_at = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (UniqueConstraint("user_id", "content_id", name="uq_user_content_rank"),)

    user = relationship("User")
    content = relationship("Content")

    def __repr__(self):
        return f"<UserContentRank user={self.user_id} content={self.content_id} score={self.rank_score}>"
