"""Unit tests for EmbeddingRepository and embedding staleness in ContentRepository."""

import json

from app.models.content import Content
from app.repositories.content_repo import ContentRepository
from app.repositories.embedding_repo import EmbeddingRepository
from app.services.providers.base import NormalizedContent


def _make_content(
    db_session,
    *,
    title: str = "Test Movie",
    content_type: str = "movie",
    description: str | None = None,
    genres: str | None = None,
    embedding=None,
    embedding_hash: str | None = None,
) -> Content:
    content = Content(
        title=title,
        content_type=content_type,
        description=description,
        genres=genres,
        embedding=embedding,
        embedding_hash=embedding_hash,
    )
    db_session.add(content)
    db_session.flush()
    return content


class TestGetEmbeddingCandidates:
    def test_returns_rows_with_null_embedding(self, db_session):
        repo = EmbeddingRepository(db_session)
        needs = _make_content(db_session, title="Needs Embedding")
        _make_content(
            db_session,
            title="Already Embedded",
            embedding=[0.1] * 768,
            embedding_hash="abc123",
        )

        candidates = repo.get_embedding_candidates()

        assert [c.id for c in candidates] == [needs.id]

    def test_returns_rows_with_null_embedding_hash(self, db_session):
        repo = EmbeddingRepository(db_session)
        stale = _make_content(
            db_session,
            title="Stale Hash",
            embedding=[0.2] * 768,
            embedding_hash=None,
        )
        _make_content(
            db_session,
            title="Fresh",
            embedding=[0.3] * 768,
            embedding_hash="fresh",
        )

        candidates = repo.get_embedding_candidates()

        assert [c.id for c in candidates] == [stale.id]

    def test_respects_limit(self, db_session):
        repo = EmbeddingRepository(db_session)
        for i in range(5):
            _make_content(db_session, title=f"Movie {i}")

        candidates = repo.get_embedding_candidates(limit=2)

        assert len(candidates) == 2

    def test_excludes_fully_embedded_rows(self, db_session):
        repo = EmbeddingRepository(db_session)
        _make_content(
            db_session,
            title="Done",
            embedding=[0.4] * 768,
            embedding_hash="done",
        )

        candidates = repo.get_embedding_candidates()

        assert candidates == []


class TestSetEmbedding:
    def test_persists_vector_hash_and_timestamp(self, db_session):
        repo = EmbeddingRepository(db_session)
        content = _make_content(db_session, title="To Embed")
        vector = [0.5] * 768

        repo.set_embedding(content, vector, "hash123")
        db_session.flush()
        db_session.refresh(content)

        assert list(content.embedding) == vector
        assert content.embedding_hash == "hash123"
        assert content.embedding_updated_at is not None


class TestMergeIntoStaleness:
    def test_nulls_embedding_hash_when_description_filled(self, db_session):
        content = _make_content(
            db_session,
            title="Sparse",
            embedding=[0.1] * 768,
            embedding_hash="old-hash",
        )
        repo = ContentRepository(db_session)
        nc = NormalizedContent(
            title="Sparse",
            content_type="movie",
            provider="tmdb",
            description="A thrilling adventure.",
        )

        repo._merge_into(content, nc)
        db_session.flush()
        db_session.refresh(content)

        assert content.description == "A thrilling adventure."
        assert content.embedding_hash is None
        assert content.embedding is not None

    def test_nulls_embedding_hash_when_genres_filled(self, db_session):
        content = _make_content(
            db_session,
            title="No Genres Yet",
            embedding=[0.2] * 768,
            embedding_hash="old-hash",
        )
        repo = ContentRepository(db_session)
        nc = NormalizedContent(
            title="No Genres Yet",
            content_type="movie",
            provider="tmdb",
            genres=["Action", "Drama"],
        )

        repo._merge_into(content, nc)
        db_session.flush()
        db_session.refresh(content)

        assert json.loads(content.genres) == ["Action", "Drama"]
        assert content.embedding_hash is None

    def test_does_not_null_hash_when_only_poster_url_changes(self, db_session):
        content = _make_content(
            db_session,
            title="Has Poster Gap",
            embedding=[0.3] * 768,
            embedding_hash="keep-me",
            description="Existing overview",
            genres=json.dumps(["Comedy"]),
        )
        repo = ContentRepository(db_session)
        nc = NormalizedContent(
            title="Has Poster Gap",
            content_type="movie",
            provider="tmdb",
            poster_url="https://example.com/poster.jpg",
        )

        repo._merge_into(content, nc)
        db_session.flush()
        db_session.refresh(content)

        assert content.poster_url == "https://example.com/poster.jpg"
        assert content.embedding_hash == "keep-me"
