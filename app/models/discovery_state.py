"""
Tracks per-provider discovery progress so each run fetches the next page
of content rather than re-scanning the same data.

Once all pages have been exhausted (empty page returned), ``fully_synced``
is set to True and subsequent runs switch to "refresh mode" — fetching
page 1 to pick up newly registered content on the source platform.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint

from app.database import Base


def utc_now():
    return datetime.now(UTC)


class DiscoveryState(Base):
    __tablename__ = "discovery_state"

    id = Column(Integer, primary_key=True)
    provider = Column(String(30), nullable=False)
    content_type = Column(String(20), nullable=False)  # "movie" or "tv_show"
    last_page = Column(Integer, nullable=False, default=0)
    total_items_fetched = Column(Integer, nullable=False, default=0)
    fully_synced = Column(Boolean, nullable=False, default=False)
    last_synced_at = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (UniqueConstraint("provider", "content_type", name="uq_provider_content_type"),)

    def __repr__(self):
        return f"<DiscoveryState {self.provider}/{self.content_type} page={self.last_page} synced={self.fully_synced}>"
