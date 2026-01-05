"""
Database configuration and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager
from typing import Generator

from app.config import settings

# Create engine with appropriate settings for SQLite/PostgreSQL
# Note: echo=False to reduce log noise (ROLLBACK/COMMIT messages)
if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=False  # Disabled to reduce log noise
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False  # Disabled to reduce log noise
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes to get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions (for use outside of routes)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(drop_all: bool = False):
    """Initialize database tables
    
    Args:
        drop_all: If True, drops all tables before creating (use only in development)
    """
    # Import all models to register them with Base
    from app.models import user, content, library, recommendation, gossip  # noqa: F401
    
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    
    Base.metadata.create_all(bind=engine)

