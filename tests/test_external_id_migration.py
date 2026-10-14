"""The external-id migration: backfill from the old columns, refuse unclean data, roll back.

Runs against a throwaway SQLite file; never the real database.
"""

import pytest
from sqlalchemy import create_engine, inspect, text

import app.database as database
import app.models  # noqa: F401
from alembic import command

AFTER = "8d4f2b6a1c07"  # this migration; later ones drop the columns it reads
BEFORE = "5c1e7a9d3b24"  # content refresh state: the head before this migration


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'ext.db'}"
    monkeypatch.setattr(database.settings, "database_url", url)
    eng = create_engine(url)
    monkeypatch.setattr(database, "engine", eng)
    command.upgrade(database._alembic_config(), BEFORE)
    yield eng
    eng.dispose()


def seed(engine, rows):
    with engine.begin() as conn:
        for title, kind, ids in rows:
            cols = ", ".join(["title", "content_type", *ids])
            marks = ", ".join(f":{c}" for c in ["title", "content_type", *ids])
            conn.execute(
                text(f"INSERT INTO content ({cols}) VALUES ({marks})"),  # noqa: S608
                {"title": title, "content_type": kind, **ids},
            )


def upgrade_to_head():
    command.upgrade(database._alembic_config(), AFTER)


def external_rows(engine):
    with engine.connect() as conn:
        return set(conn.execute(text("SELECT provider, kind, external_id FROM content_external_id")).all())


def test_backfill_copies_every_existing_id(engine):
    seed(
        engine,
        [
            ("Alpha", "movie", {"tvdb_id": 7, "imdb_id": "tt1"}),
            ("Beta", "tv_show", {"tmdb_id": 7, "tvmaze_id": 4}),
            ("A Book", "book", {"isbn": "9780"}),
            ("Plain", "movie", {}),
        ],
    )

    upgrade_to_head()

    assert external_rows(engine) == {
        ("tvdb", "movie", "7"),
        ("imdb", "movie", "tt1"),
        ("tmdb", "tv_show", "7"),
        ("tvmaze", "tv_show", "4"),
        ("isbn", "book", "9780"),
    }


def test_backfill_row_count_matches_what_the_audit_counts_as_ids(engine):
    seed(
        engine,
        [
            ("A Movie", "movie", {"tmdb_id": 300}),
            ("A Show", "tv_show", {"tmdb_id": 300}),  # same number, other type: allowed
            ("Gamma", "movie", {"tvdb_id": 8, "imdb_id": "tt8"}),
        ],
    )
    with engine.connect() as conn:
        id_values = sum(
            conn.execute(text(f"SELECT COUNT({c}) FROM content")).scalar()  # noqa: S608
            for c in ("tmdb_id", "imdb_id", "tvdb_id", "tvmaze_id", "isbn")
        )

    upgrade_to_head()

    assert len(external_rows(engine)) == id_values == 4


def test_backfill_is_batched_across_id_ranges(engine, monkeypatch):
    import importlib.util
    from pathlib import Path

    path = next(Path("alembic/versions").glob("*external_id*.py"))
    spec = importlib.util.spec_from_file_location("ext_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "BATCH", 3)
    seed(engine, [(f"T{i}", "movie", {"tvdb_id": i}) for i in range(1, 11)])

    with engine.begin() as conn:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

    assert len(external_rows(engine)) == 10


def test_refuses_to_run_when_the_audit_would_not_be_clean(engine):
    seed(engine, [("Alpha", "movie", {"tvdb_id": 7}), ("Beta", "movie", {"tvdb_id": 7})])

    with pytest.raises(Exception, match="duplicate"):
        upgrade_to_head()

    assert "content_external_id" not in inspect(engine).get_table_names()


def test_database_refuses_a_second_row_with_the_same_triple(engine):
    seed(engine, [("Alpha", "movie", {"tvdb_id": 7})])
    upgrade_to_head()

    with pytest.raises(Exception, match="UNIQUE|unique"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO content_external_id (provider, kind, external_id, content_id) VALUES ('tvdb','movie','7',1)"
            )
        )


def test_downgrade_drops_the_table_and_keeps_the_old_columns(engine):
    seed(engine, [("Alpha", "movie", {"tvdb_id": 7})])
    upgrade_to_head()

    command.downgrade(database._alembic_config(), BEFORE)

    assert "content_external_id" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT tvdb_id FROM content WHERE title='Alpha'")).scalar() == 7


def test_single_alembic_head():
    from alembic.script import ScriptDirectory

    assert len(ScriptDirectory.from_config(database._alembic_config()).get_heads()) == 1
