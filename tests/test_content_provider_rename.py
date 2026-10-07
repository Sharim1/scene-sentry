"""SCE-5: ``Content.source`` / ``NormalizedContent.source`` renamed to ``provider``.

These pin the post-rename contract: the column and dataclass field are named
``provider``, ``source`` is gone, and the ingestion path persists it.
"""

from app.models.content import Content
from app.repositories.content_repo import ContentRepository
from app.services.providers.base import NormalizedContent


def test_content_model_has_provider_column_not_source():
    columns = {c.name for c in Content.__table__.columns}
    assert "provider" in columns
    assert "source" not in columns


def test_normalized_content_uses_provider_field():
    nc = NormalizedContent(title="Dune", content_type="movie", provider="tmdb")
    assert nc.provider == "tmdb"
    assert not hasattr(nc, "source")


def test_upsert_normalized_persists_provider(db_session):
    repo = ContentRepository(db_session)
    nc = NormalizedContent(title="Dune", content_type="movie", provider="tmdb", tmdb_id=438631)

    saved = repo.upsert_normalized(nc)
    db_session.flush()

    assert saved.provider == "tmdb"
