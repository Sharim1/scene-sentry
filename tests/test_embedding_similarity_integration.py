"""Postgres+pgvector integration tests for embedding similarity (SCE-33)."""

import os

import pytest

pytestmark = pytest.mark.integration

TEST_DB = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def pg_session():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set; skipping pgvector integration test")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.database import Base

    engine = create_engine(TEST_DB)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres/pgvector unavailable: {exc}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _vec(first: float, second: float = 0.0) -> list[float]:
    """Build a 768-d vector with energy in the first two dimensions."""
    values = [0.0] * 768
    values[0] = first
    values[1] = second
    return values


class TestFindSimilarIntegration:
    def test_returns_closer_neighbours_before_distant_ones(self, pg_session):
        from app.models.content import Content
        from app.repositories.embedding_repo import EmbeddingRepository

        action1 = Content(
            title="Action One",
            content_type="movie",
            embedding=_vec(1.0, 0.0),
            embedding_hash="a1",
        )
        action2 = Content(
            title="Action Two",
            content_type="movie",
            embedding=_vec(0.99, 0.01),
            embedding_hash="a2",
        )
        documentary = Content(
            title="Nature Doc",
            content_type="movie",
            embedding=_vec(0.0, 1.0),
            embedding_hash="d1",
        )
        pg_session.add_all([action1, action2, documentary])
        pg_session.commit()

        repo = EmbeddingRepository(pg_session)
        neighbours = repo.find_similar(action1.embedding, limit=5, exclude_id=action1.id)

        titles = [c.title for c in neighbours]
        assert titles.index("Action Two") < titles.index("Nature Doc")

    def test_honours_content_type_filter(self, pg_session):
        from app.models.content import Content
        from app.repositories.embedding_repo import EmbeddingRepository

        movie = Content(
            title="Movie Match",
            content_type="movie",
            embedding=_vec(1.0),
            embedding_hash="m1",
        )
        show = Content(
            title="Show Match",
            content_type="tv_show",
            embedding=_vec(0.99),
            embedding_hash="s1",
        )
        pg_session.add_all([movie, show])
        pg_session.commit()

        repo = EmbeddingRepository(pg_session)
        neighbours = repo.find_similar(movie.embedding, limit=5, content_type="movie")

        assert all(c.content_type == "movie" for c in neighbours)
        assert neighbours[0].title == "Movie Match"

    def test_honours_exclude_id(self, pg_session):
        from app.models.content import Content
        from app.repositories.embedding_repo import EmbeddingRepository

        source = Content(
            title="Source",
            content_type="movie",
            embedding=_vec(1.0),
            embedding_hash="src",
        )
        neighbour = Content(
            title="Neighbour",
            content_type="movie",
            embedding=_vec(0.95),
            embedding_hash="n1",
        )
        pg_session.add_all([source, neighbour])
        pg_session.commit()

        repo = EmbeddingRepository(pg_session)
        neighbours = repo.find_similar(source.embedding, limit=5, exclude_id=source.id)

        assert all(c.id != source.id for c in neighbours)
