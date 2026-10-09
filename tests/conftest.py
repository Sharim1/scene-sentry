"""Shared test fixtures."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ENV", "development")
os.environ.setdefault("DEBUG", "false")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base


@pytest.fixture(scope="session")
def engine():
    """In-memory SQLite engine for the entire test session."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # pysqlite does not handle SAVEPOINT / transactions correctly by default, so rows written
    # inside a savepoint would survive the per-test rollback. This is SQLAlchemy's documented recipe.
    @event.listens_for(engine, "connect")
    def _no_implicit_begin(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _explicit_begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    """Per-test database session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def fake_embedder():
    """Deterministic stand-in for GoogleGenerativeAIEmbeddings — no network."""

    class FakeEmbedder:
        def __init__(self):
            self.embed_calls = 0

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.embed_calls += 1
            return [self._vec(t) for t in texts]

        def embed_query(self, text: str) -> list[float]:
            return self._vec(text)

        @staticmethod
        def _vec(text: str) -> list[float]:
            seed = (len(text) % 7) + 1
            return [float((i * seed) % 5) for i in range(768)]

    return FakeEmbedder()
