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

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI routes to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions (for use outside of routes)."""
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
    """Add columns that may be missing from existing tables.

    SQLAlchemy's create_all only creates tables that don't exist yet; it won't
    ALTER existing ones.  This function inspects each table and issues
    ALTER TABLE ADD COLUMN for any column defined in the model but absent in
    the database.  Safe to run repeatedly (idempotent).
    """
    insp = inspect(engine)
    existing_tables = insp.get_table_names()

    add_columns: list[tuple[str, str, str]] = [
        ("users", "timezone", "VARCHAR(50) DEFAULT 'UTC'"),
    ]

    alter_types: list[tuple[str, str, str]] = [
        ("reminders", "scheduled_time", "TIMESTAMPTZ"),
    ]

    with engine.begin() as conn:
        for table, column, col_type in add_columns:
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table)}
            if column not in existing_cols:
                stmt = f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}'
                conn.execute(text(stmt))
                logger.info("Migration: added %s.%s", table, column)

        for table, column, new_type in alter_types:
            if table not in existing_tables:
                continue
            result = conn.execute(text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = :tbl AND column_name = :col"
            ), {"tbl": table, "col": column})
            row = result.fetchone()
            if row and row[0] != "timestamp with time zone":
                stmt = (
                    f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
                    f"TYPE {new_type} USING \"{column}\" AT TIME ZONE current_setting('timezone')"
                )
                conn.execute(text(stmt))
                logger.info("Migration: altered %s.%s to %s", table, column, new_type)

        # Fix FK constraints that need ON DELETE behaviour
        fk_fixes: list[tuple[str, str, str, str, str]] = [
            # (table, constraint_name, column, references, on_delete)
            ("notifications", "notifications_reminder_id_fkey", "reminder_id", "reminders(id)", "SET NULL"),
        ]
        for table, constraint, column, references, on_delete in fk_fixes:
            if table not in existing_tables:
                continue
            row = conn.execute(text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conname = :name"
            ), {"name": constraint}).fetchone()
            # 'a' = NO ACTION (default), 'n' = SET NULL, 'c' = CASCADE
            if row and row[0] != "n":
                conn.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"'))
                conn.execute(text(
                    f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" '
                    f'FOREIGN KEY ("{column}") REFERENCES {references} ON DELETE {on_delete}'
                ))
                logger.info("Migration: updated FK %s to ON DELETE %s", constraint, on_delete)


def init_db(drop_all: bool = False):
    """Initialize database tables.

    Args:
        drop_all: If True, drops all tables before creating (use only in development)
    """
    from app.models import user, content, episode, library, gossip, reminder, notification, ranking, discovery_state  # noqa: F401

    if drop_all:
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)
    _run_migrations()
