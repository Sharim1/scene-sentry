"""External ids only identify a title within its own type.

TVDB and TMDb number movies and series separately, so the same number can exist for
both. Matching ids across types made discovery treat a new movie as "already stored"
(merging it into a show) and drop it. Driven through the public sync with a real test
database.
"""

import pytest

from app.models.content import Content
from tests.discovery_helpers import FakeProvider, FakeTVDBWithDates, item, provider_with, stored, sync


def add_row(db_session, **kw):
    row = Content(**kw)
    db_session.add(row)
    db_session.commit()
    return row


class TestSameNumberDifferentType:
    @pytest.mark.parametrize("id_field", ["tvdb_id", "tmdb_id"])
    def test_a_new_movie_is_stored_when_a_show_has_the_same_id(self, db_session, id_field):
        add_row(db_session, title="Some Show", content_type="tv_show", **{id_field: 300})

        sync(db_session, provider_with("movie", "tvdb", [item("A Movie", "movie", **{id_field: 300})]))

        assert {r.title for r in stored(db_session)} == {"Some Show", "A Movie"}

    @pytest.mark.parametrize("id_field", ["tvdb_id", "tmdb_id"])
    def test_a_new_show_is_stored_when_a_movie_has_the_same_id(self, db_session, id_field):
        add_row(db_session, title="Some Movie", content_type="movie", **{id_field: 300})

        sync(db_session, provider_with("tv_show", "tvdb", [item("A Show", "tv_show", **{id_field: 300})]))

        assert {r.title for r in stored(db_session)} == {"Some Movie", "A Show"}

    def test_a_movie_and_a_show_with_the_same_id_in_one_run_are_both_stored(self, db_session):
        provider = FakeProvider(
            "tvdb", movies=[item("Movie 5", "movie", tvdb_id=5)], shows=[item("Show 5", "tv_show", tvdb_id=5)]
        )

        sync(db_session, provider)

        assert {r.title for r in stored(db_session)} == {"Movie 5", "Show 5"}

    def test_a_new_movie_still_gets_its_release_date_looked_up_when_a_show_has_its_id(self, db_session):
        add_row(db_session, title="Some Show", content_type="tv_show", tvdb_id=300)
        provider = FakeTVDBWithDates(
            {300: ("2024-05-06", "https://img/300.jpg")}, movies=[item("A Movie", "movie", tvdb_id=300, year=None)]
        )

        sync(db_session, provider)

        movie = [r for r in stored(db_session, "movie")][0]
        assert provider.asked_release == [300]
        assert movie.release_date == "2024-05-06"


class TestStillTheSameTitleWhenItShouldBe:
    def test_syncing_the_same_title_twice_does_not_duplicate_it(self, db_session):
        provider = provider_with("movie", "tvdb", [item("Same", "movie", tvdb_id=9)])

        sync(db_session, provider)
        sync(db_session, provider)

        assert len(stored(db_session, "movie")) == 1

    def test_an_id_less_title_with_the_same_name_and_year_merges_into_the_existing_row(self, db_session):
        add_row(db_session, title="Silo", content_type="tv_show", tvdb_id=5, release_date="2023-05-05")

        sync(
            db_session,
            provider_with("tv_show", "tmdb", [item("Silo", "tv_show", provider="tmdb", year=2023, tmdb_id=99)]),
        )

        rows = stored(db_session, "tv_show")
        assert len(rows) == 1
        assert (rows[0].tvdb_id, rows[0].tmdb_id) == (5, 99)


class TestDifferentIdsAreDifferentTitles:
    def test_two_titles_with_the_same_name_and_year_but_different_ids_are_both_stored(self, db_session):
        add_row(db_session, title="The Voice", content_type="tv_show", tvdb_id=10, release_date="2011-04-26")

        sync(db_session, provider_with("tv_show", "tvdb", [item("The Voice", "tv_show", year=2011, tvdb_id=11)]))

        assert {r.tvdb_id for r in stored(db_session, "tv_show")} == {10, 11}

    def test_two_such_titles_arriving_in_one_run_are_both_stored(self, db_session):
        items = [
            item("The Voice", "tv_show", year=2011, tvdb_id=10),
            item("The Voice", "tv_show", year=2011, tvdb_id=11),
        ]

        sync(db_session, provider_with("tv_show", "tvdb", items))

        assert {r.tvdb_id for r in stored(db_session, "tv_show")} == {10, 11}
