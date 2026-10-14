"""External-id table: one row per (provider, kind, external id), refused twice by the database."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.content import Content
from app.models.external_id import ContentExternalId
from app.repositories.content_repo import ContentRepository
from app.services.providers.base import NormalizedContent


def add_title(db_session, title="Dune", content_type="movie", **kw):
    row = Content(title=title, content_type=content_type, **kw)
    db_session.add(row)
    db_session.flush()
    return row


def nc(title, content_type="movie", **ids):
    return NormalizedContent(title=title, content_type=content_type, provider="tvdb", year=2020, **ids)


def triples(db_session):
    db_session.expire_all()
    return {(r.provider, r.kind, r.external_id, r.content_id) for r in db_session.query(ContentExternalId).all()}


# ---- the database rule ---- #


def test_same_triple_twice_is_refused_by_the_database(db_session):
    a = add_title(db_session, "Alpha")
    b = add_title(db_session, "Beta")
    db_session.add(ContentExternalId(provider="tvdb", kind="movie", external_id="7", content_id=a.id))
    db_session.flush()

    db_session.add(ContentExternalId(provider="tvdb", kind="movie", external_id="7", content_id=b.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_number_under_another_kind_or_provider_is_allowed(db_session):
    a = add_title(db_session, "A Movie", "movie")
    b = add_title(db_session, "A Show", "tv_show")
    db_session.add_all(
        [
            ContentExternalId(provider="tmdb", kind="movie", external_id="300", content_id=a.id),
            ContentExternalId(provider="tmdb", kind="tv_show", external_id="300", content_id=b.id),
            ContentExternalId(provider="tvdb", kind="movie", external_id="300", content_id=a.id),
        ]
    )
    db_session.flush()


# ---- writes through the repository ---- #


def test_bulk_save_writes_the_table(db_session):
    ContentRepository(db_session).bulk_upsert_normalized(
        [nc("Alpha", tvdb_id=7, imdb_id="tt1"), nc("Beta", "tv_show", tmdb_id=9, tvmaze_id=4)]
    )

    alpha = db_session.query(Content).filter_by(title="Alpha").one()
    beta = db_session.query(Content).filter_by(title="Beta").one()
    assert triples(db_session) == {
        ("tvdb", "movie", "7", alpha.id),
        ("imdb", "movie", "tt1", alpha.id),
        ("tmdb", "tv_show", "9", beta.id),
        ("tvmaze", "tv_show", "4", beta.id),
    }


def test_single_save_writes_the_table(db_session):
    row = ContentRepository(db_session).upsert_normalized(nc("Alpha", tvdb_id=7))

    assert triples(db_session) == {("tvdb", "movie", "7", row.id)}


def test_merging_a_new_id_into_an_existing_title_adds_its_row(db_session):
    repo = ContentRepository(db_session)
    first = repo.upsert_normalized(nc("Alpha", tvdb_id=7))

    again = repo.upsert_normalized(nc("Alpha", tvdb_id=7, imdb_id="tt1"))

    assert again.id == first.id
    assert triples(db_session) == {("tvdb", "movie", "7", first.id), ("imdb", "movie", "tt1", first.id)}


def test_bulk_merge_of_a_new_id_adds_its_row(db_session):
    repo = ContentRepository(db_session)
    first = repo.upsert_normalized(nc("Alpha", tvdb_id=7))

    repo.bulk_upsert_normalized([nc("Alpha", tvdb_id=7, imdb_id="tt1")])

    assert triples(db_session) == {("tvdb", "movie", "7", first.id), ("imdb", "movie", "tt1", first.id)}


def test_saving_the_same_batch_twice_does_not_duplicate_rows(db_session):
    repo = ContentRepository(db_session)
    repo.bulk_upsert_normalized([nc("Alpha", tvdb_id=7)])
    repo.bulk_upsert_normalized([nc("Alpha", tvdb_id=7)])

    assert len(triples(db_session)) == 1


# ---- reads through the table ---- #


def test_matching_by_id_reads_the_table(db_session):
    repo = ContentRepository(db_session)
    row = repo.upsert_normalized(nc("Alpha", tvdb_id=7))

    assert repo.find_existing(nc("Different name", tvdb_id=7)).id == row.id
    repo.bulk_upsert_normalized([nc("Other name", tvdb_id=7)])
    assert db_session.query(Content).count() == 1


def test_a_numeric_id_only_matches_within_its_type(db_session):
    repo = ContentRepository(db_session)
    movie = repo.upsert_normalized(nc("A Movie", "movie", tmdb_id=300))

    show = repo.upsert_normalized(nc("A Show", "tv_show", tmdb_id=300))

    assert show.id != movie.id


def test_content_has_no_provider_id_columns_ids_live_only_in_the_table(db_session):
    from app.models.content import Content

    for old in ("tmdb_id", "imdb_id", "tvdb_id", "tvmaze_id", "isbn"):
        assert not hasattr(Content, old)
