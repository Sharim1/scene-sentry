"""Unit tests for embedding text building, hashing, and refresh job logic."""

import json
from unittest.mock import patch

from app.models.content import Content
from app.services.embedding_service import (
    EmbeddingService,
    build_embedding_text,
    embedding_hash,
)


def _make_content(**kwargs) -> Content:
    defaults = {
        "title": "Inception",
        "content_type": "movie",
        "description": None,
        "genres": None,
    }
    defaults.update(kwargs)
    return Content(**defaults)


class TestBuildEmbeddingText:
    def test_includes_title_type_genres_and_overview(self):
        content = _make_content(
            description="A mind-bending thriller.",
            genres=json.dumps(["Sci-Fi", "Action"]),
        )

        text = build_embedding_text(content)

        assert text == ("Title: Inception\nType: movie\nGenres: Sci-Fi, Action\nOverview: A mind-bending thriller.")

    def test_omits_genres_and_overview_when_absent(self):
        content = _make_content()

        text = build_embedding_text(content)

        assert text == "Title: Inception\nType: movie"

    def test_is_deterministic(self):
        content = _make_content(
            description="Same every time.",
            genres=json.dumps(["Drama"]),
        )

        assert build_embedding_text(content) == build_embedding_text(content)


class TestEmbeddingHash:
    def test_is_stable_for_same_input(self):
        text = "Title: Foo\nType: movie"

        assert embedding_hash(text) == embedding_hash(text)

    def test_changes_when_input_changes(self):
        first = embedding_hash("Title: Foo\nType: movie")
        second = embedding_hash("Title: Bar\nType: movie")

        assert first != second


class TestRefreshEmbeddings:
    def test_embeds_all_candidates_and_commits(self, db_session, fake_embedder):
        for title in ("Alpha", "Beta", "Gamma"):
            db_session.add(Content(title=title, content_type="movie"))
        db_session.flush()

        svc = EmbeddingService(db_session, embedder=fake_embedder)
        embedded = svc.refresh_embeddings()

        assert embedded == 3
        assert fake_embedder.embed_calls == 1
        rows = db_session.query(Content).order_by(Content.id).all()
        for row in rows:
            assert row.embedding is not None
            assert len(row.embedding) == 768
            assert row.embedding_hash is not None
            assert row.embedding_updated_at is not None

    def test_second_run_is_idempotent(self, db_session, fake_embedder):
        db_session.add(Content(title="Solo", content_type="movie"))
        db_session.flush()

        svc = EmbeddingService(db_session, embedder=fake_embedder)
        assert svc.refresh_embeddings() == 1
        assert fake_embedder.embed_calls == 1

        assert svc.refresh_embeddings() == 0
        assert fake_embedder.embed_calls == 1

    def test_no_op_when_embedding_disabled(self, db_session, fake_embedder):
        db_session.add(Content(title="Disabled", content_type="movie"))
        db_session.flush()

        svc = EmbeddingService(db_session, embedder=fake_embedder)
        with patch("app.services.embedding_service.settings.embedding_enabled", False):
            assert svc.refresh_embeddings() == 0

        assert fake_embedder.embed_calls == 0

    def test_no_op_when_embedder_is_none(self, db_session):
        db_session.add(Content(title="No Key", content_type="movie"))
        db_session.flush()

        svc = EmbeddingService(db_session)
        with patch("app.services.embedding_service.settings.gemini_api_key", None):
            assert svc.refresh_embeddings() == 0
