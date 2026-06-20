"""Regression tests for the Alembic-backed schema bootstrap in ``init_db``.

These lock in the three startup paths that ``init_db`` must distinguish:

* fresh database          -> ``alembic upgrade head``
* legacy (pre-Alembic) DB -> ``alembic stamp head`` (adopt, don't recreate)
* ``drop_all=True``       -> rebuild from migrations

Each test runs against an isolated temp SQLite file with ``settings.database_url``
and the module-level engine monkeypatched to point at it, so the real
application/CI database is never touched.
"""

import pytest
from sqlalchemy import create_engine, inspect, text

import app.database as database
import app.models  # noqa: F401  (registers all tables on Base.metadata)

HEAD_REVISION = "0001_baseline"
CORE_TABLES = {"users", "content", "reminders", "notifications", "library_items"}


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point settings + the module engine at a throwaway SQLite file."""
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setattr(database.settings, "database_url", url)
    test_engine = create_engine(url)
    monkeypatch.setattr(database, "engine", test_engine)
    yield test_engine
    test_engine.dispose()


def _stamped_revision(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_fresh_database_upgrades_to_head(temp_db):
    database.init_db()

    tables = set(inspect(temp_db).get_table_names())
    assert "alembic_version" in tables
    assert tables >= CORE_TABLES
    assert _stamped_revision(temp_db) == HEAD_REVISION


def test_init_db_is_idempotent(temp_db):
    database.init_db()
    database.init_db()  # must not raise on an already-migrated DB

    assert _stamped_revision(temp_db) == HEAD_REVISION


def test_legacy_database_is_adopted_via_stamp(temp_db):
    # Simulate a pre-Alembic database: tables exist (legacy create_all) but
    # there is no alembic_version table yet.
    database.Base.metadata.create_all(bind=temp_db)
    assert "alembic_version" not in set(inspect(temp_db).get_table_names())

    database.init_db()

    # Adopted in place — version table created, schema NOT recreated.
    assert _stamped_revision(temp_db) == HEAD_REVISION


def test_drop_all_rebuilds_schema(temp_db):
    database.init_db()
    database.init_db(drop_all=True)

    tables = set(inspect(temp_db).get_table_names())
    assert tables >= CORE_TABLES
    assert _stamped_revision(temp_db) == HEAD_REVISION
