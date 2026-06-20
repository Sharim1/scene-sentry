"""
Database configuration and session management
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

# Repo root (parent of the ``app`` package) — where alembic.ini lives.
_REPO_ROOT = Path(__file__).resolve().parent.parent

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


def _alembic_config():
    """Build a programmatic Alembic config pointing at the repo's alembic.ini."""
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    # Use absolute script location so this works regardless of the process CWD.
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


def init_db(drop_all: bool = False):
    """Bring the database schema up to date via Alembic.

    Schema is now owned by Alembic (``alembic/versions``) rather than
    ``create_all`` + hand-rolled ALTERs. This function is the single startup
    entrypoint (used by the FastAPI lifespan and ``manage.py``) and is safe to
    run repeatedly:

    * **Fresh database** — ``alembic upgrade head`` builds everything.
    * **Legacy database** (tables exist from the old ``create_all`` path but no
      ``alembic_version`` table) — it is *adopted* via ``alembic stamp head``
      instead of re-running the baseline, which would fail on existing tables.
    * **Already migrated** — ``alembic upgrade head`` applies any new revisions.

    Args:
        drop_all: If True, drops all tables first, then rebuilds from migrations
            (development only).
    """
    from alembic import command

    cfg = _alembic_config()
    insp = inspect(engine)

    if drop_all:
        # Ensure all models are registered before dropping.
        import app.models  # noqa: F401

        Base.metadata.drop_all(bind=engine)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        command.upgrade(cfg, "head")
        logger.info("Database reset and migrated to head")
        return

    tables = set(insp.get_table_names())
    if "alembic_version" in tables:
        command.upgrade(cfg, "head")
    elif "users" in tables:
        # Pre-Alembic database created by the legacy bootstrap — adopt it.
        command.stamp(cfg, "head")
        logger.info("Adopted existing database into Alembic (stamped head)")
    else:
        command.upgrade(cfg, "head")
        logger.info("Fresh database migrated to head")
