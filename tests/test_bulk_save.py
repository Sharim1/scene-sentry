"""Saving a batch of discovered titles must take a handful of statements, not a few per title.

From the Oracle box every database round trip costs ~270 ms, so the old per-title save managed about
one title a second. These tests count the SQL statements the save sends and check the batched
save still behaves like the per-title one.
"""

import pytest
from sqlalchemy import event

from app.models.content import Content
from app.repositories.content_repo import ContentRepository
from app.services.providers.base import NormalizedContent


def movie(i, **kw):
    return NormalizedContent(title=f"Movie {i}", content_type="movie", provider="tvdb", year=2020, tvdb_id=i, **kw)


@pytest.fixture()
def statements(db_session):
    """Collects every SQL statement the session sends while the test body runs."""
    seen: list[str] = []
    conn = db_session.get_bind()

    def record(connection, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    yield seen
    event.remove(conn, "before_cursor_execute", record)


def stored(db_session):
    db_session.flush()
    db_session.expire_all()
    return db_session.query(Content).all()


class TestStatementCount:
    @pytest.mark.parametrize("n", [50, 500, 1200])
    def test_new_titles_do_not_cost_statements_per_title(self, db_session, statements, n):
        saved = ContentRepository(db_session).bulk_upsert_normalized([movie(i) for i in range(1, n + 1)])

        assert saved == n
        assert len(stored(db_session)) == n
        assert len(statements) <= 25, f"{len(statements)} statements for {n} titles"

    def test_titles_that_already_exist_are_also_batched(self, db_session, statements):
        repo = ContentRepository(db_session)
        repo.bulk_upsert_normalized([movie(i) for i in range(1, 401)])
        statements.clear()

        repo.bulk_upsert_normalized([movie(i, poster_url=f"https://img/{i}.jpg") for i in range(1, 401)])

        assert len(statements) <= 25, f"{len(statements)} statements for 400 existing titles"


class TestSameResultsAsTheSingleTitleSave:
    def test_a_blank_on_an_existing_title_is_filled_and_nothing_is_overwritten(self, db_session):
        repo = ContentRepository(db_session)
        repo.upsert_normalized(movie(1, description="original"))
        db_session.commit()

        repo.bulk_upsert_normalized([movie(1, description="replacement", poster_url="https://img/1.jpg")])

        row = [r for r in stored(db_session) if r.tvdb_id == 1][0]
        assert row.description == "original"
        assert row.poster_url == "https://img/1.jpg"

    def test_ids_only_match_within_the_same_type(self, db_session):
        repo = ContentRepository(db_session)
        repo.bulk_upsert_normalized(
            [NormalizedContent(title="A Show", content_type="tv_show", provider="tvdb", tvdb_id=7)]
        )

        repo.bulk_upsert_normalized([movie(7)])

        assert {(r.content_type, r.tvdb_id) for r in stored(db_session)} == {("tv_show", 7), ("movie", 7)}

    def test_two_titles_with_the_same_name_and_year_but_different_ids_are_both_saved(self, db_session):
        repo = ContentRepository(db_session)
        a = NormalizedContent(title="The Voice", content_type="tv_show", provider="tvdb", year=2011, tvdb_id=1)
        b = NormalizedContent(title="The Voice", content_type="tv_show", provider="tvdb", year=2011, tvdb_id=2)

        repo.bulk_upsert_normalized([a, b])

        assert {r.tvdb_id for r in stored(db_session)} == {1, 2}

    def test_an_id_less_title_merges_into_a_pending_title_from_the_same_batch(self, db_session):
        repo = ContentRepository(db_session)
        a = NormalizedContent(title="Silo", content_type="tv_show", provider="tvdb", year=2023, tvdb_id=5)
        b = NormalizedContent(title="Silo", content_type="tv_show", provider="tmdb", year=2023, tmdb_id=99)

        repo.bulk_upsert_normalized([a, b])

        rows = stored(db_session)
        assert len(rows) == 1 and (rows[0].tvdb_id, rows[0].tmdb_id) == (5, 99)

    def test_new_rows_get_their_timestamps(self, db_session):
        ContentRepository(db_session).bulk_upsert_normalized([movie(1)])

        row = stored(db_session)[0]
        assert row.created_at is not None and row.updated_at is not None and row.is_adaptation is False

    def test_one_bad_title_does_not_stop_the_rest(self, db_session):
        good_before, bad, good_after = movie(1), movie(2), movie(3)
        bad.title = None  # cannot be saved

        saved = ContentRepository(db_session).bulk_upsert_normalized([good_before, bad, good_after])

        assert saved == 2
        assert {r.tvdb_id for r in stored(db_session)} == {1, 3}
