"""Enrichment must not hold the worker for an hour.

From the Oracle box every database round trip costs ~270 ms. Saving a show's episodes one at a
time made a single enrichment run last longer than its 15 minute schedule and starved the
reminder task. These tests count statements and check the time budget.
"""

import pytest
from sqlalchemy import event

from app.models.content import Content
from app.models.episode import Episode
from app.repositories.episode_repo import EpisodeRepository
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedEpisode


def ep(season, number, **kw):
    return NormalizedEpisode(season_number=season, episode_number=number, title=f"S{season}E{number}", **kw)


def show(db_session, tvdb_id=1, **kw):
    row = Content(title=f"Show {tvdb_id}", content_type="tv_show", tvdb_id=tvdb_id, provider="tvdb", **kw)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def statements(db_session):
    seen: list[str] = []
    conn = db_session.get_bind()

    def record(connection, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    yield seen
    event.remove(conn, "before_cursor_execute", record)


def rows(db_session, content_id):
    db_session.flush()
    db_session.expire_all()
    return db_session.query(Episode).filter_by(content_id=content_id).all()


class TestEpisodeSaveIsBatched:
    @pytest.mark.parametrize("n", [10, 500])
    def test_new_episodes_do_not_cost_statements_per_episode(self, db_session, statements, n):
        content = show(db_session)
        statements.clear()

        saved = EpisodeRepository(db_session).bulk_upsert(content.id, [ep(1 + i // 25, 1 + i % 25) for i in range(n)])

        assert saved == n
        assert len(rows(db_session, content.id)) == n
        assert len(statements) <= 10, f"{len(statements)} statements for {n} episodes"

    def test_existing_episodes_are_also_batched(self, db_session, statements):
        content = show(db_session)
        repo = EpisodeRepository(db_session)
        repo.bulk_upsert(content.id, [ep(1, i) for i in range(1, 201)])
        statements.clear()

        repo.bulk_upsert(content.id, [ep(1, i, runtime=42) for i in range(1, 201)])

        assert len(statements) <= 10, f"{len(statements)} statements for 200 existing episodes"


class TestSameResultsAsTheSingleEpisodeSave:
    def test_a_blank_on_an_existing_episode_is_filled_and_nothing_is_overwritten(self, db_session):
        content = show(db_session)
        repo = EpisodeRepository(db_session)
        repo.bulk_upsert(content.id, [ep(1, 1, runtime=30)])

        repo.bulk_upsert(
            content.id,
            [NormalizedEpisode(season_number=1, episode_number=1, title="Other", runtime=99, air_date="2020-01-02")],
        )

        (row,) = rows(db_session, content.id)
        assert row.title == "S1E1"
        assert row.runtime == 30
        assert row.air_date == "2020-01-02"

    def test_the_same_episode_twice_in_one_list_is_saved_once(self, db_session):
        content = show(db_session)

        EpisodeRepository(db_session).bulk_upsert(content.id, [ep(1, 1), ep(1, 1, runtime=40)])

        (row,) = rows(db_session, content.id)
        assert row.runtime == 40

    def test_episodes_of_another_show_are_left_alone(self, db_session):
        a, b = show(db_session, 1), show(db_session, 2)
        repo = EpisodeRepository(db_session)
        repo.bulk_upsert(a.id, [ep(1, 1, runtime=20)])

        repo.bulk_upsert(b.id, [ep(1, 1, runtime=50)])

        assert rows(db_session, a.id)[0].runtime == 20
        assert rows(db_session, b.id)[0].runtime == 50

    def test_a_long_title_is_cut_to_fit(self, db_session):
        content = show(db_session)

        EpisodeRepository(db_session).bulk_upsert(
            content.id, [ep(1, 1).__class__(season_number=1, episode_number=1, title="x" * 400)]
        )

        assert len(rows(db_session, content.id)[0].title) == 300

    def test_returns_how_many_episodes_were_given(self, db_session):
        content = show(db_session)

        assert EpisodeRepository(db_session).bulk_upsert(content.id, []) == 0


class FakeProvider:
    name = "tvdb"

    def __init__(self, episodes_per_show=3):
        self.calls = 0
        self.n = episodes_per_show

    def get_details(self, ext_id):
        return None

    def get_episodes(self, ext_id):
        self.calls += 1
        return [ep(1, i) for i in range(1, self.n + 1)]


class TestTimeBudget:
    def service(self, db_session, provider):
        svc = ContentDiscoveryService.__new__(ContentDiscoveryService)
        svc.db = db_session
        svc.providers = [provider]
        from app.repositories.content_repo import ContentRepository

        svc.repo = ContentRepository(db_session)
        return svc

    def test_stops_starting_new_titles_once_the_budget_is_spent(self, db_session):
        for i in range(1, 6):
            show(db_session, i)
        provider = FakeProvider()
        svc = self.service(db_session, provider)
        clock = iter([0, 0, 1, 2, 100, 100, 100, 100, 100])

        done = svc.enrich_sparse_content(batch_size=5, time_budget_seconds=10, now=lambda: next(clock))

        assert done < 5
        assert provider.calls == done

    def test_no_budget_means_the_whole_batch(self, db_session):
        for i in range(1, 4):
            show(db_session, i)
        provider = FakeProvider()

        done = self.service(db_session, provider).enrich_sparse_content(batch_size=3)

        assert done == 3
