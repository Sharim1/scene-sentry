"""content external id table

One row per provider id of a title, with a database unique rule on
(provider, kind, external_id) (ADR-0006, issue #79). ``provider`` is the id source
(tmdb, imdb, tvdb, tvmaze, isbn), ``kind`` is the content type the id numbers (providers
number movies and series separately), ``external_id`` is the id as text. The id columns on
``content`` stay as copies and the application writes both.

Backfill: the existing id columns are copied with set-based ``INSERT ... SELECT`` statements,
one per provider per range of ``content.id`` (``BATCH`` ids at a time), so ~534k titles are
never loaded into Python. The table is new, so nothing else reads or locks it while it fills.

Precondition: the catalog audit (``app/services/catalog_audit.py``, issue #73) must report
``duplicate_provider_ids: 0``. This migration repeats that check first and stops with an
error, before creating anything, if one provider id is still used by several titles of the
same kind. (Same number across a movie and a series is fine: they are different kinds.)
After the upgrade, the row count equals the number of non-empty id values in ``content``
(the audit's definition of "an id").

BEFORE RUNNING IN PRODUCTION
  1. Take a snapshot / backup of the database (e.g. a Render Postgres snapshot or
     ``pg_dump``) and note its name here and in the ticket.
  2. Run the audit against the real database and get ``duplicate_provider_ids`` to 0.
  3. Run ``alembic upgrade head``, then compare
     ``SELECT provider, count(*) FROM content_external_id GROUP BY 1`` with
     ``SELECT count(tmdb_id), count(imdb_id), count(tvdb_id), count(tvmaze_id), count(isbn) FROM content``.

ROLLBACK
  ``alembic downgrade 5c1e7a9d3b24`` drops ``content_external_id``. The id columns on
  ``content`` are never modified by this migration, so no data is lost and the previous
  application version keeps working. If something else went wrong, restore the snapshot.

Revision ID: 8d4f2b6a1c07
Revises: 5c1e7a9d3b24
Create Date: 2026-10-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d4f2b6a1c07"
down_revision: str | None = "5c1e7a9d3b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "content_external_id"
BATCH = 50_000  # content ids per backfill statement

# provider -> (column on content, is the column text)
PROVIDER_COLUMNS = {
    "tmdb": ("tmdb_id", False),
    "imdb": ("imdb_id", True),
    "tvdb": ("tvdb_id", False),
    "tvmaze": ("tvmaze_id", False),
    "isbn": ("isbn", True),
}


def _has_value(column: str, is_text: bool) -> str:
    return f"{column} IS NOT NULL AND {column} <> ''" if is_text else f"{column} IS NOT NULL"


def _refuse_unclean_data(bind: sa.Connection) -> None:
    problems = []
    for provider, (column, is_text) in PROVIDER_COLUMNS.items():
        count = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM content WHERE {_has_value(column, is_text)} "  # noqa: S608
                f"GROUP BY content_type, {column} HAVING COUNT(*) > 1) AS d"
            )
        ).scalar()
        if count:
            problems.append(f"{provider}: {count}")
    if problems:
        raise RuntimeError(
            "Cannot add the unique rule: duplicate provider ids exist ("
            + ", ".join(problems)
            + "). Run the catalog audit and resolve them first."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _refuse_unclean_data(bind)

    op.create_table(
        TABLE,
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(50), nullable=False),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("provider", "kind", "external_id", name="pk_content_external_id"),
    )

    lo, hi = bind.execute(sa.text("SELECT MIN(id), MAX(id) FROM content")).one()
    if lo is not None:
        start = lo - 1
        while start < hi:
            end = start + BATCH
            for provider, (column, is_text) in PROVIDER_COLUMNS.items():
                bind.execute(
                    sa.text(
                        f"INSERT INTO {TABLE} (provider, kind, external_id, content_id) "  # noqa: S608
                        f"SELECT '{provider}', content_type, CAST({column} AS VARCHAR(50)), id FROM content "
                        f"WHERE id > :start AND id <= :end AND {_has_value(column, is_text)}"
                    ),
                    {"start": start, "end": end},
                )
            start = end

    # Built after the load: cheaper than maintaining it row by row.
    op.create_index("ix_content_external_id_content_id", TABLE, ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_content_external_id_content_id", TABLE)
    op.drop_table(TABLE)
