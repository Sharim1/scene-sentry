"""content refresh state

Per-title refresh record (ADR-0006, issue #72).

Safe on ~534k rows: every added column is nullable or has a constant default, which
PostgreSQL 11+ adds as a metadata-only change (no table rewrite), and there is no
backfill. NULL ``next_refresh_at`` means "never scheduled", so existing titles read as
due without touching a single row. The index is built CONCURRENTLY so writes are not
blocked.

BEFORE RUNNING IN PRODUCTION: take a snapshot/backup of the database first.

Revision ID: 5c1e7a9d3b24
Revises: 2af305e18dc8
Create Date: 2026-10-14 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5c1e7a9d3b24"
down_revision: str | None = "2af305e18dc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_content_next_refresh_at"


def upgrade() -> None:
    op.add_column("content", sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content", sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content", sa.Column("refresh_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("content", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("content", sa.Column("refresh_locked", sa.Boolean(), nullable=False, server_default=sa.false()))

    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(INDEX, "content", ["next_refresh_at"], postgresql_concurrently=True, if_not_exists=True)
    else:
        op.create_index(INDEX, "content", ["next_refresh_at"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(INDEX, "content", postgresql_concurrently=True, if_exists=True)
    else:
        op.drop_index(INDEX, "content")
    for column in ("refresh_locked", "last_error", "refresh_attempts", "next_refresh_at", "last_refreshed_at"):
        op.drop_column("content", column)
