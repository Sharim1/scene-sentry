"""drop the old provider id columns from content

The contract step of ADR-0006 (issue #89, spec #67). Provider ids now live only in
``content_external_id``; nothing reads or writes ``content.tmdb_id / imdb_id / tvdb_id /
tvmaze_id / isbn`` any more (#88 moved the reads, this change removed the dual writes).
This drops those five columns and the indexes on them. The ``episodes`` id columns are
a different thing and stay.

Safety check: before changing anything, the migration counts the non-empty id values still
in the old columns and the rows in ``content_external_id``. If the table has FEWER rows than
there are old values, some id exists only in the old columns and dropping them would lose
it, so the migration raises and changes nothing. (More rows in the table is fine: the
application keeps adding ids there.)

SNAPSHOT FIRST, THEN RUN (owner steps)
  1. Take a snapshot / backup of the production database (a Render Postgres snapshot or
     ``pg_dump``) and note its name in the ticket. This drop is the one step that is not
     undone by simply deploying the old code.
  2. Deploy the application version that no longer touches the old columns.
  3. Run ``alembic upgrade head``. Dropping columns takes a short exclusive lock on
     ``content``; run it at a quiet moment.
  This migration must never be run against production from a test or a script. Tests use a
  throwaway SQLite file.

ROLLBACK
  ``alembic downgrade 9e5a3c7b2d18`` re-adds the five columns as nullable, rebuilds the four
  indexes the baseline had (tmdb, imdb, tvdb, tvmaze; isbn never had one), and refills the
  columns from ``content_external_id`` (set-based ``UPDATE`` statements, ``BATCH`` content
  ids at a time). Where a title has no row for a provider the column stays NULL. Redeploy the
  previous application version afterwards. If something else went wrong, restore the snapshot.

Revision ID: a1b6c4d8e2f7
Revises: 9e5a3c7b2d18
Create Date: 2026-10-15 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b6c4d8e2f7"
down_revision: str | None = "9e5a3c7b2d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "content_external_id"
BATCH = 50_000  # content ids per refill statement

# provider -> (column on content, column is text, indexed in the baseline)
PROVIDER_COLUMNS = {
    "tmdb": ("tmdb_id", False, True),
    "imdb": ("imdb_id", True, True),
    "tvdb": ("tvdb_id", False, True),
    "tvmaze": ("tvmaze_id", False, True),
    "isbn": ("isbn", True, False),
}


def _has_value(column: str, is_text: bool) -> str:
    return f"{column} IS NOT NULL AND {column} <> ''" if is_text else f"{column} IS NOT NULL"


def _refuse_if_ids_would_be_lost(bind: sa.Connection) -> None:
    old_values = sum(
        bind.execute(sa.text(f"SELECT COUNT(*) FROM content WHERE {_has_value(col, is_text)}")).scalar()  # noqa: S608
        for col, is_text, _ in PROVIDER_COLUMNS.values()
    )
    table_rows = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar()  # noqa: S608
    if table_rows < old_values:
        raise RuntimeError(
            f"Refusing to drop the old id columns: content_external_id has {table_rows} rows but the old "
            f"columns hold {old_values} ids, so some ids exist only in the old columns. "
            "Backfill content_external_id first (see the 8d4f2b6a1c07 migration)."
        )


def upgrade() -> None:
    _refuse_if_ids_would_be_lost(op.get_bind())

    with op.batch_alter_table("content") as batch_op:
        for column, _, indexed in PROVIDER_COLUMNS.values():
            if indexed:
                batch_op.drop_index(f"ix_content_{column}")
        for column, _, _ in PROVIDER_COLUMNS.values():
            batch_op.drop_column(column)


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("content") as batch_op:
        for column, is_text, _ in PROVIDER_COLUMNS.values():
            batch_op.add_column(sa.Column(column, sa.String(20) if is_text else sa.Integer(), nullable=True))
    for column, _, indexed in PROVIDER_COLUMNS.values():
        if indexed:
            op.create_index(f"ix_content_{column}", "content", [column])

    lo, hi = bind.execute(sa.text("SELECT MIN(id), MAX(id) FROM content")).one()
    if lo is None:
        return
    start = lo - 1
    while start < hi:
        end = start + BATCH
        for provider, (column, is_text, _) in PROVIDER_COLUMNS.items():
            value = "e.external_id" if is_text else "CAST(e.external_id AS INTEGER)"
            bind.execute(
                sa.text(
                    f"UPDATE content SET {column} = ("  # noqa: S608
                    f"SELECT MIN({value}) FROM {TABLE} e "
                    f"WHERE e.content_id = content.id AND e.provider = '{provider}' AND e.kind = content.content_type"
                    f") WHERE id > :start AND id <= :end"
                ),
                {"start": start, "end": end},
            )
        start = end
