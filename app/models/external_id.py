"""One row per provider id of a title (ADR-0006, issue #79).

The database refuses a second row with the same (provider, kind, external_id): the same
provider id can never point at two titles. ``provider`` is the id's source (tmdb, imdb,
tvdb, tvmaze, isbn), ``kind`` is the content type it numbers (movie, tv_show, book) because
providers number movies and series separately, ``external_id`` is the id as text.
The id columns on ``content`` stay as copies and are written together with this table.
"""

from sqlalchemy import Column, ForeignKey, Integer, String

from app.database import Base


class ContentExternalId(Base):
    __tablename__ = "content_external_id"

    provider = Column(String(20), primary_key=True)
    kind = Column(String(20), primary_key=True)
    external_id = Column(String(50), primary_key=True)
    content_id = Column(Integer, ForeignKey("content.id", ondelete="CASCADE"), nullable=False, index=True)

    def __repr__(self):
        return f"<ContentExternalId {self.provider}/{self.kind}/{self.external_id} -> {self.content_id}>"
