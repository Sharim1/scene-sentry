"""A batch insert must give each new row the provider ids of its own item (ADR-0006, story 8).

Postgres does not promise that RETURNING lists rows in VALUES order or that ids rise with it, so the
repository may not rely on order to pair new rows with the ids that were sent for them. The
``reversed_inserts`` fixture simulates a database that stores a multi-row INSERT in the opposite order.
"""

import pytest
from sqlalchemy.orm import Session

from app.models.content import Content
from app.models.external_id import ContentExternalId
from app.repositories.content_repo import ContentRepository, ExternalIdError
from app.services.providers.base import NormalizedContent
from tests.id_helpers import id_of


@pytest.fixture()
def reversed_inserts(monkeypatch):
    real = Session.execute

    def execute(self, statement, *a, **kw):
        multi = getattr(statement, "_multi_values", None)
        if getattr(statement, "table", None) is Content.__table__ and multi and len(multi[0]) > 1:
            statement = statement.table.insert().values(list(reversed(multi[0]))).returning(*statement._returning)
        return real(self, statement, *a, **kw)

    monkeypatch.setattr(Session, "execute", execute)


def movie(title, release_date, **ids):
    return NormalizedContent(
        title=title, content_type="movie", provider="tvdb", year=int(release_date[:4]), release_date=release_date, **ids
    )


def test_same_title_in_different_years_keeps_each_years_own_ids(db_session, reversed_inserts):
    items = [movie("Dune", "1984-12-14", tvdb_id=1), movie("Dune", "2021-10-22", tvdb_id=2)]

    ContentRepository(db_session).bulk_upsert_normalized(items)

    by_year = {r.release_date[:4]: id_of(db_session, r, "tvdb") for r in db_session.query(Content).all()}
    assert by_year == {"1984": 1, "2021": 2}


def test_same_title_and_date_with_different_ids_keeps_each_own_ids(db_session, reversed_inserts):
    items = [movie("Dune", "2021-10-22", tvdb_id=1), movie("Dune", "2021-10-22", tvdb_id=2)]

    ContentRepository(db_session).bulk_upsert_normalized(items)

    rows = db_session.query(Content).all()
    assert len(rows) == 2
    assert {id_of(db_session, r, "tvdb") for r in rows} == {1, 2}


def test_a_failed_external_id_write_does_not_leave_a_title_saved_without_its_ids(db_session, monkeypatch):
    # tvdb id 7 already belongs to another title, but the lookup before the insert did not see it (a race)
    other = Content(title="Other", content_type="movie")
    db_session.add(other)
    db_session.flush()
    db_session.add(ContentExternalId(provider="tvdb", kind="movie", external_id="7", content_id=other.id))
    db_session.flush()
    monkeypatch.setattr("app.repositories.content_repo._ExistingIndex.match", lambda self, nc: None)

    with pytest.raises(ExternalIdError):
        ContentRepository(db_session).bulk_upsert_normalized([movie("Racer", "2020-01-01", tvdb_id=7)])

    assert db_session.query(Content).filter_by(title="Racer").count() == 0


def test_an_imdb_id_names_one_title_whatever_its_type(db_session):
    """IMDb ids are global: the resolver and the stored ids both treat tt1 as one title, never two."""
    repo = ContentRepository(db_session)
    film = Content(title="Film", content_type="movie")
    show = Content(title="Show", content_type="tv_show")
    db_session.add_all([film, show])
    db_session.flush()
    repo.record_external_ids([(film.id, "movie", {"imdb": "tt1"})])

    with pytest.raises(ExternalIdError):
        repo.record_external_ids([(show.id, "tv_show", {"imdb": "tt1"})])

    assert db_session.query(ContentExternalId).filter_by(provider="imdb", external_id="tt1").count() == 1


def test_recording_the_same_imdb_id_again_for_its_own_title_is_harmless(db_session):
    repo = ContentRepository(db_session)
    film = Content(title="Film", content_type="movie")
    db_session.add(film)
    db_session.flush()

    repo.record_external_ids([(film.id, "movie", {"imdb": "tt1"})])
    repo.record_external_ids([(film.id, "movie", {"imdb": "tt1"})])

    assert db_session.query(ContentExternalId).filter_by(provider="imdb").count() == 1
