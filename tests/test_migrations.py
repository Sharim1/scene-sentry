"""Regression tests for the Alembic-backed schema bootstrap in ``init_db``.

These lock in the three startup paths that ``init_db`` must distinguish:

* fresh database          -> ``alembic upgrade head``
* legacy (pre-Alembic) DB -> stamp baseline, then upgrade (adopt + apply later
  migrations, preserving data)
* ``drop_all=True``       -> rebuild from migrations

Each test runs against an isolated temp SQLite file with ``settings.database_url``
and the module-level engine monkeypatched to point at it, so the real
application/CI database is never touched.
"""

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

import app.database as database
import app.models  # noqa: F401  (registers all tables on Base.metadata)
from alembic import command

BASELINE_REVISION = "0001_baseline"
CORE_TABLES = {"users", "content", "reminders", "notifications", "library_items"}


def _head_revision() -> str:
    return ScriptDirectory.from_config(database._alembic_config()).get_current_head()


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


def _content_columns(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("content")}


def test_fresh_database_upgrades_to_head(temp_db):
    database.init_db()

    tables = set(inspect(temp_db).get_table_names())
    assert "alembic_version" in tables
    assert tables >= CORE_TABLES
    assert _stamped_revision(temp_db) == _head_revision()
    # End state reflects the full migration chain (post-rename).
    assert "provider" in _content_columns(temp_db)
    assert "source" not in _content_columns(temp_db)


def test_init_db_is_idempotent(temp_db):
    database.init_db()
    database.init_db()  # must not raise on an already-migrated DB

    assert _stamped_revision(temp_db) == _head_revision()


def test_legacy_database_is_adopted_and_migrated(temp_db):
    # Build a realistic pre-Alembic database: the baseline schema (which still
    # has content.source), seeded with a row, and with no alembic_version table.
    command.upgrade(database._alembic_config(), BASELINE_REVISION)
    assert "source" in _content_columns(temp_db)
    with temp_db.begin() as conn:
        conn.exec_driver_sql("INSERT INTO content (title, content_type, source) VALUES ('Dune', 'movie', 'tmdb')")
    with temp_db.begin() as conn:
        conn.exec_driver_sql("DROP TABLE alembic_version")
    assert "alembic_version" not in set(inspect(temp_db).get_table_names())

    database.init_db()

    # Adopted AND brought up to head: column renamed, data preserved.
    assert _stamped_revision(temp_db) == _head_revision()
    cols = _content_columns(temp_db)
    assert "provider" in cols
    assert "source" not in cols
    with temp_db.connect() as conn:
        provider = conn.execute(text("SELECT provider FROM content WHERE title = 'Dune'")).scalar()
    assert provider == "tmdb"


def test_drop_all_rebuilds_schema(temp_db):
    database.init_db()
    database.init_db(drop_all=True)

    tables = set(inspect(temp_db).get_table_names())
    assert tables >= CORE_TABLES
    assert _stamped_revision(temp_db) == _head_revision()
    assert "provider" in _content_columns(temp_db)
