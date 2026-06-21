"""Shared test fixtures."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ENV", "development")
os.environ.setdefault("DEBUG", "false")

import pytest
from sqlalchemy import create_engine
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
