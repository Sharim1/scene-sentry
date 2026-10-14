"""Read-only audit of what would break a unique rule on (provider, kind, external id)."""

from app.models.content import Content
from app.services.catalog_audit import audit_catalog
from tests.id_helpers import add_title


def add(db_session, title, content_type="movie", **kw):
    row = Content(title=title, content_type=content_type, **kw)
    db_session.add(row)
    db_session.commit()
    return row


class TestSameNumberForMovieAndShow:
    def test_reports_the_shared_number(self, db_session):
        add_title(db_session, "A Movie", "movie", ids={"tmdb": 300})
        add_title(db_session, "A Show", "tv_show", ids={"tmdb": 300})

        report = audit_catalog(db_session)

        assert report.cross_type_ids.count == 1
        sample = report.cross_type_ids.samples[0]
        assert (sample["provider"], sample["external_id"]) == ("tmdb", "300")
        assert sorted(sample["titles"]) == ["A Movie", "A Show"]

    def test_distinct_numbers_report_nothing(self, db_session):
        add_title(db_session, "Alpha", ids={"tvdb": 7})
        add_title(db_session, "Beta", ids={"tvdb": 8})
        add_title(db_session, "A Show", "tv_show", ids={"tvdb": 7, "tmdb": 9})

        report = audit_catalog(db_session)

        assert report.cross_type_ids.count == 1  # tvdb 7 on a movie and a show
        assert report.likely_duplicates.count == 0

    def test_a_clean_catalog_reports_nothing(self, db_session):
        add_title(db_session, "Alpha", ids={"tvdb": 7})
        add_title(db_session, "Beta", ids={"tvdb": 8})

        assert audit_catalog(db_session).cross_type_ids.count == 0

    def test_books_are_not_screened(self, db_session):
        add_title(db_session, "A Book", "book", ids={"isbn": "9780"})
        add_title(db_session, "A Movie", "movie", ids={"isbn": "9780"})

        assert audit_catalog(db_session).cross_type_ids.count == 0


class TestLikelyDuplicates:
    def test_same_title_year_and_type_is_flagged_ignoring_case_and_spaces(self, db_session):
        add(db_session, "Dune", "movie", release_date="2021-10-22")
        add(db_session, " dune ", "movie", release_date="2021-09-01")

        report = audit_catalog(db_session)

        assert report.likely_duplicates.count == 1
        assert report.likely_duplicates.samples[0]["year"] == "2021"

    def test_different_year_or_type_is_not_flagged(self, db_session):
        add(db_session, "Dune", "movie", release_date="2021-10-22")
        add(db_session, "Dune", "movie", release_date="1984-12-14")
        add(db_session, "Dune", "tv_show", release_date="2021-10-22")

        assert audit_catalog(db_session).likely_duplicates.count == 0

    def test_sample_size_is_capped_but_count_is_full(self, db_session):
        for i in range(5):
            add(db_session, f"T{i}", release_date="2000-01-01")
            add(db_session, f"T{i}", release_date="2000-02-01")

        report = audit_catalog(db_session, sample_limit=2)

        assert report.likely_duplicates.count == 5
        assert len(report.likely_duplicates.samples) == 2


class TestReadOnly:
    def test_audit_changes_nothing(self, db_session):
        add_title(db_session, "A Movie", "movie", ids={"tmdb": 300})
        add_title(db_session, "A Show", "tv_show", ids={"tmdb": 300})
        before = db_session.query(Content.id, Content.title).order_by(Content.id).all()

        audit_catalog(db_session)

        assert not db_session.new and not db_session.dirty and not db_session.deleted
        assert db_session.query(Content.id, Content.title).order_by(Content.id).all() == before


class TestRunReadOnly:
    def test_run_leaves_no_changes_and_formats_counts(self, db_session):
        from app.services.catalog_audit import format_report, run_read_only

        add_title(db_session, "A Movie", "movie", ids={"tmdb": 300})
        add_title(db_session, "A Show", "tv_show", ids={"tmdb": 300})

        report = run_read_only(db_session)
        text = format_report(report)

        assert report.cross_type_ids.count == 1
        assert "cross_type_ids: 1" in text
        assert "A Movie" in text and "A Show" in text
