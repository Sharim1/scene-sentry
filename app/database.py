"""
Database configuration and session management
"""

import base64
import logging
import os
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
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
# FastAPI Cloud cold starts sometimes fail DNS to the Supabase pooler for a few
# seconds; retry instead of crashing the replica (which leaves the previous
# bundle serving).
_DB_CONNECT_ATTEMPTS = 6
_DB_CONNECT_BASE_DELAY_S = 2

def tls_connect_args(cfg) -> dict:
    """Write the configured base64 TLS material to a private dir and return libpq args.

    Returns an empty dict when no TLS material is configured, so local
    development and SQLite are unaffected. The directory is created with mode
    0700 and each file with 0600; it is never removed, because the driver reads
    the files on every new connection.
    """
    if not cfg.database_ssl_ca_b64:
        return {}
    tls_dir = Path(tempfile.mkdtemp(prefix="scene-sentry-db-tls-"))
    args = {}
    for name, value in (
        ("sslrootcert", cfg.database_ssl_ca_b64),
        ("sslcert", cfg.database_ssl_cert_b64),
        ("sslkey", cfg.database_ssl_key_b64),
    ):
        path = tls_dir / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(base64.b64decode(value))
        args[name] = str(path)
    return args


engine = create_engine(
    settings.database_url,
    connect_args=tls_connect_args(settings),
    pool_size=3,
    max_overflow=2,
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
    if engine.dialect.name != "postgresql":
        _run_migrations(drop_all)
        return

    last_error: OperationalError | None = None
    for attempt in range(1, _DB_CONNECT_ATTEMPTS + 1):
        try:
            with engine.connect() as lock_conn:
                lock_conn.exec_driver_sql(
                    "SELECT pg_advisory_lock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,)
                )
                try:
                    _run_migrations(drop_all)
                finally:
                    lock_conn.exec_driver_sql(
                        "SELECT pg_advisory_unlock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,)
                    )
            return
        except OperationalError as exc:
            last_error = exc
            engine.dispose()
            logger.warning(
                "Postgres unavailable on startup (attempt %s/%s)",
                attempt,
                _DB_CONNECT_ATTEMPTS,
            )
            if attempt < _DB_CONNECT_ATTEMPTS:
                time.sleep(_DB_CONNECT_BASE_DELAY_S * attempt)
    assert last_error is not None
    raise last_error


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
