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

# Serialises ``alembic upgrade`` across concurrently booting app replicas.
# FastAPI Cloud's scale-to-zero can cold-start up to two web replicas at once,
# and Alembic does not self-serialise DDL across processes. A Postgres advisory
# lock is a cross-session mutex: the first replica migrates while the others
# block, then run an idempotent no-op upgrade. SQLite (dev/test) is single-writer
# so it skips the lock. Value is an arbitrary, stable application-wide constant.
_MIGRATION_ADVISORY_LOCK_KEY = 728914

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

    On Postgres the whole upgrade runs under a session-level advisory lock so
    concurrently booting replicas can't race on DDL (see
    ``_MIGRATION_ADVISORY_LOCK_KEY``). SQLite runs it directly.

    Args:
        drop_all: If True, drops all tables first, then rebuilds from migrations
            (development only).
    """
    if engine.dialect.name == "postgresql":
        with engine.connect() as lock_conn:
            lock_conn.exec_driver_sql("SELECT pg_advisory_lock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,))
            try:
                _run_migrations(drop_all)
            finally:
                lock_conn.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,))
    else:
        _run_migrations(drop_all)


def _run_migrations(drop_all: bool = False):
    """Apply Alembic migrations. Callers hold the advisory lock on Postgres."""
    from alembic.script import ScriptDirectory

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
        # Pre-Alembic database created by the legacy bootstrap. Its schema
        # matches the baseline revision, so stamp the baseline (without
        # re-creating tables) and then apply any later migrations.
        base_rev = ScriptDirectory.from_config(cfg).get_bases()[0]
        command.stamp(cfg, base_rev)
        command.upgrade(cfg, "head")
        logger.info("Adopted existing database into Alembic (stamped %s, upgraded head)", base_rev)
    else:
        command.upgrade(cfg, "head")
        logger.info("Fresh database migrated to head")
