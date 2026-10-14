"""A title the identity resolver could not place (ADR-0006, issue #83).

The sync parks it here with the reason instead of guessing, merging or dropping it.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


def utc_now():
    return datetime.now(UTC)


class ReviewItem(Base):
    __tablename__ = "catalog_review"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content_type = Column(String(20), nullable=False)
    provider = Column(String(30), nullable=True)
    # Same title with the same facts has the same fingerprint, so a re-run adds nothing new.
    fingerprint = Column(String(40), nullable=False, unique=True)
    reason = Column(Text, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    def __repr__(self):
        return f"<ReviewItem {self.content_type} {self.title!r}>"
