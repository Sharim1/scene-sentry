"""Titles the resolver calls a conflict are parked on a review list, not guessed, merged or dropped.

Driven through the scheduled sync with fake providers and a real test database; the list is
read through ``list_review``.
"""

from app.services.review_list import format_review, list_review
from tests.discovery_helpers import FakeProvider, item, stored, sync
from tests.id_helpers import add_title


class TestConflictingTitleIsParked:
    def test_a_title_whose_ids_disagree_with_an_earlier_one_is_listed_with_its_reason_and_not_saved(self, db_session):
        provider = FakeProvider(
            "tvdb",
            shows=[
                item("Alpha", "tv_show", tvdb_id=5, imdb_id="tt1"),
                item("Beta", "tv_show", tvdb_id=6, imdb_id="tt1"),
            ],
        )

        sync(db_session, provider)

        assert [r.title for r in stored(db_session, "tv_show")] == ["Alpha"]
        parked = list_review(db_session)
        assert [e.title for e in parked] == ["Beta"]
        assert "Alpha" in parked[0].reason

    def test_running_the_job_again_does_not_list_the_same_title_twice(self, db_session):
        provider = FakeProvider(
            "tvdb",
            shows=[
                item("Alpha", "tv_show", tvdb_id=5, imdb_id="tt1"),
                item("Beta", "tv_show", tvdb_id=6, imdb_id="tt1"),
            ],
        )

        sync(db_session, provider)
        sync(db_session, provider)

        assert [e.title for e in list_review(db_session)] == ["Beta"]
        assert len(stored(db_session, "tv_show")) == 1


class TestConflictWithStoredTitles:
    def test_a_title_whose_ids_belong_to_two_stored_titles_is_listed_and_neither_is_changed(self, db_session):
        add_title(db_session, "Alpha", "tv_show", ids={"tvdb": 5})
        add_title(db_session, "Beta", "tv_show", ids={"imdb": "tt1"})

        sync(db_session, FakeProvider("tvdb", shows=[item("Gamma", "tv_show", tvdb_id=5, imdb_id="tt1")]))

        assert sorted(r.title for r in stored(db_session, "tv_show")) == ["Alpha", "Beta"]
        parked = list_review(db_session)
        assert [e.title for e in parked] == ["Gamma"]
        assert "Alpha" in parked[0].reason and "Beta" in parked[0].reason

    def test_a_title_sharing_one_id_but_disagreeing_on_another_is_listed_not_merged(self, db_session):
        add_title(db_session, "Alpha", "tv_show", ids={"tvdb": 5, "imdb": "ttA"})

        sync(db_session, FakeProvider("tvdb", shows=[item("Alpha", "tv_show", tvdb_id=5, imdb_id="ttB")]))

        assert [r.title for r in stored(db_session, "tv_show")] == ["Alpha"]
        assert [e.title for e in list_review(db_session)] == ["Alpha"]


class TestReadingTheList:
    def test_the_printed_list_shows_each_title_with_its_reason(self, db_session):
        sync(
            db_session,
            FakeProvider(
                "tvdb",
                shows=[
                    item("Alpha", "tv_show", tvdb_id=5, imdb_id="tt1"),
                    item("Beta", "tv_show", tvdb_id=6, imdb_id="tt1"),
                ],
            ),
        )

        text = format_review(list_review(db_session))

        assert "Beta" in text and "tv_show" in text and "Alpha" in text
        assert "1 title" in text

    def test_an_empty_list_says_so(self):
        assert format_review([]) == "Nothing waiting for review."
