"""Test setup for provider ids: they live in the external-id table, not on the title row."""

from app.models.content import Content
from app.models.external_id import ContentExternalId


def add_title(db, title, content_type="movie", ids=None, **fields):
    """Add a title whose provider ids exist only in the external-id table.

    ``ids`` is {provider: id}, e.g. {"tvdb": 7, "imdb": "tt1"}. The old id columns are left empty
    so a test passes only if the code under test reads the table.
    """
    row = Content(title=title, content_type=content_type, **fields)
    db.add(row)
    db.flush()
    for provider, value in (ids or {}).items():
        db.add(ContentExternalId(provider=provider, kind=content_type, external_id=str(value), content_id=row.id))
    db.commit()
    return row


def add_row_with_ids(db, **fields):
    """Add a title from keyword fields where ``tvdb_id=7`` style values go into the external-id table."""
    ids = {kind: fields.pop(f"{kind}_id") for kind in ("tmdb", "imdb", "tvdb", "tvmaze") if fields.get(f"{kind}_id")}
    for kind in ("tmdb", "imdb", "tvdb", "tvmaze"):
        fields.pop(f"{kind}_id", None)
    return add_title(db, fields.pop("title"), fields.pop("content_type", "movie"), ids=ids, **fields)


def id_of(db, row, provider):
    """The row's id for a provider from the external-id table (int for numeric providers), or None."""
    db.expire_all()
    found = (
        db.query(ContentExternalId.external_id)
        .filter(ContentExternalId.content_id == row.id, ContentExternalId.provider == provider)
        .scalar()
    )
    if found is not None and provider in ("tmdb", "tvdb", "tvmaze"):
        return int(found)
    return found
