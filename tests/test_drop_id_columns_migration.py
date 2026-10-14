"""The contract migration (issue #89): drop the old provider id columns from ``content``.

Runs against a throwaway SQLite file; never the real database and never the network.
"""

import pytest
from sqlalchemy import create_engine, inspect, text

import app.database as database
import app.models  # noqa: F401
from alembic import command

BEFORE = "9e5a3c7b2d18"  # catalog review: the head before this migration
OLD_COLUMNS = {"tmdb_id", "imdb_id", "tvdb_id", "tvmaze_id", "isbn"}


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'drop.db'}"
    monkeypatch.setattr(database.settings, "database_url", url)
    eng = create_engine(url)
    monkeypatch.setattr(database, "engine", eng)
    command.upgrade(database._alembic_config(), BEFORE)
    yield eng
    eng.dispose()


def upgrade_to_head():
    command.upgrade(database._alembic_config(), "head")


def downgrade_to_before():
    command.downgrade(database._alembic_config(), BEFORE)


def add_title(engine, title, kind="movie", old_ids=None, table_ids=None):
    """Insert a title with ids on the old columns and/or in the external-id table."""
    old_ids = old_ids or {}
    with engine.begin() as conn:
        cols = ["title", "content_type", *old_ids]
        conn.execute(
            text(f"INSERT INTO content ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"),  # noqa: S608
            {"title": title, "content_type": kind, **old_ids},
        )
        content_id = conn.execute(text("SELECT MAX(id) FROM content")).scalar()
        for provider, value in (table_ids or {}).items():
            conn.execute(
                text(
                    "INSERT INTO content_external_id (provider, kind, external_id, content_id) VALUES (:p, :k, :v, :c)"
                ),
                {"p": provider, "k": kind, "v": str(value), "c": content_id},
            )


def content_columns(engine):
    return {c["name"] for c in inspect(engine).get_columns("content")}


def test_upgrade_drops_the_old_columns_and_their_indexes(engine):
    add_title(engine, "Alpha", old_ids={"tvdb_id": 7}, table_ids={"tvdb": 7})

    upgrade_to_head()

    assert not (OLD_COLUMNS & content_columns(engine))
    indexed = {col for ix in inspect(engine).get_indexes("content") for col in ix["column_names"]}
    assert not OLD_COLUMNS & indexed
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM content")).scalar() == "Alpha"
        assert conn.execute(text("SELECT external_id FROM content_external_id")).scalar() == "7"


def test_upgrade_keeps_the_episode_id_columns(engine):
    upgrade_to_head()

    assert {"tvmaze_id", "tvdb_id", "imdb_id"} <= {c["name"] for c in inspect(engine).get_columns("episodes")}


def test_refuses_to_run_when_the_table_has_fewer_rows_than_the_old_columns(engine):
    add_title(engine, "Alpha", old_ids={"tvdb_id": 7, "imdb_id": "tt1"}, table_ids={"tvdb": 7})  # imdb missing

    with pytest.raises(RuntimeError, match="content_external_id"):
        upgrade_to_head()

    assert content_columns(engine) >= OLD_COLUMNS


def test_runs_when_the_table_has_at_least_as_many_rows(engine):
    add_title(engine, "Alpha", old_ids={"tvdb_id": 7}, table_ids={"tvdb": 7, "imdb": "tt1"})  # extra row is fine

    upgrade_to_head()

    assert not (OLD_COLUMNS & content_columns(engine))


def test_downgrade_re_adds_nullable_columns_and_refills_them_from_the_table(engine):
    add_title(engine, "Alpha", old_ids={"tvdb_id": 7, "imdb_id": "tt1"}, table_ids={"tvdb": 7, "imdb": "tt1"})
    add_title(engine, "A Book", kind="book", table_ids={"isbn": "9780"})
    add_title(engine, "A Show", kind="tv_show", table_ids={"tmdb": 300, "tvmaze": 4})
    upgrade_to_head()

    downgrade_to_before()

    assert content_columns(engine) >= OLD_COLUMNS
    with engine.connect() as conn:
        rows = {
            r.title: r
            for r in conn.execute(text("SELECT title, tmdb_id, imdb_id, tvdb_id, tvmaze_id, isbn FROM content"))
        }
    assert (rows["Alpha"].tvdb_id, rows["Alpha"].imdb_id, rows["Alpha"].tmdb_id) == (7, "tt1", None)
    assert rows["A Book"].isbn == "9780"
    assert (rows["A Show"].tmdb_id, rows["A Show"].tvmaze_id) == (300, 4)
    indexed = {col for ix in inspect(engine).get_indexes("content") for col in ix["column_names"]}
    assert {"tmdb_id", "imdb_id", "tvdb_id", "tvmaze_id"} <= indexed
