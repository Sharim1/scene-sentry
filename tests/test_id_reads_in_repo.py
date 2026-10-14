"""Matching and merging read a title's ids from the external-id table, never the old columns.

Titles here have their ids only in the table (the columns are empty), so each test passes only
if the repository reads the table. ADR-0006, issue #88.
"""

import pytest

from app.models.content import Content
from app.models.external_id import ContentExternalId
from app.repositories.content_repo import ContentRepository
from app.services.providers.base import NormalizedContent
from tests.id_helpers import add_title


def nc(title="Silo", content_type="tv_show", **ids):
    return NormalizedContent(title=title, content_type=content_type, provider="tvdb", year=2023, **ids)


def table_ids(db, content_id):
    db.expire_all()
    rows = db.query(ContentExternalId).filter_by(content_id=content_id).all()
    return {(r.provider, r.external_id) for r in rows}


def titles(db):
    db.expire_all()
    return db.query(Content).count()


@pytest.fixture(params=["single", "bulk"])
def save(request, db_session):
    """Save one item through either public entry point."""
    repo = ContentRepository(db_session)

    def _save(item):
        if request.param == "single":
            repo.upsert_normalized(item)
        else:
            assert repo.bulk_upsert_normalized([item]) == 1
        db_session.flush()

    return _save


def test_same_name_with_a_different_provider_id_is_a_different_title(db_session, save):
    add_title(db_session, "Silo", "tv_show", ids={"tvdb": 5}, release_date="2023-05-05")

    save(nc(tvdb_id=6))

    assert titles(db_session) == 2


def test_same_name_with_the_same_provider_id_is_the_same_title(db_session, save):
    add_title(db_session, "Silo", "tv_show", ids={"tvdb": 5}, release_date="2023-05-05")

    save(nc(tvdb_id=5))

    assert titles(db_session) == 1


def test_a_merge_does_not_give_a_title_a_second_id_of_a_kind_it_already_has(db_session, save):
    row = add_title(db_session, "Silo", "tv_show", ids={"imdb": "tt1", "tvdb": 5}, release_date="2023-05-05")

    save(nc(imdb_id="tt1", tvdb_id=6))

    assert table_ids(db_session, row.id) == {("imdb", "tt1"), ("tvdb", "5")}


def test_a_merge_adds_an_id_the_title_did_not_have(db_session, save):
    row = add_title(db_session, "Silo", "tv_show", ids={"imdb": "tt1"}, release_date="2023-05-05")

    save(nc(imdb_id="tt1", tvmaze_id=9))

    assert table_ids(db_session, row.id) == {("imdb", "tt1"), ("tvmaze", "9")}
