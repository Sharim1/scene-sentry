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
