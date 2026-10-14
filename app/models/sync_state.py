"""
Per-stream change-feed sync state (ADR-0006).

One row per (provider, stream), e.g. ("tvdb", "tv_show"). ``watermark`` is the bookmark:
the start time of the last run that finished successfully. It only moves forward after
a success, so a failed run is simply repeated from the same point.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.database import Base


def utc_now():
    return datetime.now(UTC)


class SyncState(Base):
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True)
    provider = Column(String(30), nullable=False)
    stream = Column(String(20), nullable=False)  # "movie" or "tv_show"
    watermark = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), nullable=False, default="idle")  # idle / ok / gap_fallback / failed
    last_error = Column(Text, nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("provider", "stream", name="uq_sync_state_provider_stream"),)

    def __repr__(self):
        return f"<SyncState {self.provider}/{self.stream} status={self.status} watermark={self.watermark}>"
