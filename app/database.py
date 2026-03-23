"""
Database configuration and session management
"""
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager
from typing import Generator

from app.config import settings

logger = logging.getLogger(__name__)

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


def _run_migrations():
    """Add columns that may be missing from existing SQLite tables.

    SQLAlchemy's create_all only creates tables that don't exist yet; it won't
    ALTER existing ones. This function inspects each table and issues ALTER TABLE
    ADD COLUMN for any column defined in the model but absent in the DB.
    """
    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    migrations: list[tuple[str, str, str]] = [
        # (table, column, DDL type + constraints)
        ("reminders", "content_id", "INTEGER REFERENCES content(id)"),
        ("reminders", "platform", "VARCHAR(50)"),
        ("reminders", "quality", "VARCHAR(50)"),
        ("reminders", "is_enabled", "BOOLEAN DEFAULT 1"),
        ("gossip", "preview_text", "TEXT"),
        ("content", "tvdb_id", "INTEGER"),
        ("content", "tvmaze_id", "INTEGER"),
        ("content", "source", "VARCHAR(20)"),
    ]

    with engine.begin() as conn:
        for table, column, col_type in migrations:
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table)}
            if column not in existing_cols:
                stmt = f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}'
                conn.execute(text(stmt))
                logger.info("Migration: added %s.%s", table, column)


def init_db(drop_all: bool = False):
    """Initialize database tables
    
    Args:
        drop_all: If True, drops all tables before creating (use only in development)
    """
    # Import all models to register them with Base
    from app.models import user, content, library, gossip, reminder, ranking, discovery_state  # noqa: F401
    
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    
    Base.metadata.create_all(bind=engine)

    _run_migrations()

