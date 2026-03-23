"""
Episode model for individual TV show episodes.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True)
    content_id = Column(Integer, ForeignKey("content.id", ondelete="CASCADE"), nullable=False, index=True)

    season_number = Column(Integer, nullable=False)
    episode_number = Column(Integer, nullable=False)
    title = Column(String(300), nullable=True)
    description = Column(Text, nullable=True)

    air_date = Column(String(20), nullable=True)     # YYYY-MM-DD
    runtime = Column(Integer, nullable=True)          # minutes
    rating = Column(Float, nullable=True)

    # External IDs for cross-platform matching
    tvmaze_id = Column(Integer, nullable=True, index=True)
    tvdb_id = Column(Integer, nullable=True, index=True)
    imdb_id = Column(String(20), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    content = relationship("Content", backref="episode_list")

    __table_args__ = (
        UniqueConstraint(
            "content_id", "season_number", "episode_number",
            name="uq_content_season_episode",
        ),
    )

    def __repr__(self):
        return f"<Episode S{self.season_number:02d}E{self.episode_number:02d} {self.title!r}>"
