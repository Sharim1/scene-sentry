"""sync state

Per-stream change-feed bookmark (ADR-0006, issue #84).

Safe on production: creates one new, empty table; no existing table is touched or rewritten.

BEFORE RUNNING IN PRODUCTION: take a snapshot/backup of the database first.

Revision ID: 8d2f4b6a1c93
Revises: 8d4f2b6a1c07
Create Date: 2026-10-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d2f4b6a1c93"
down_revision: str | None = "8d4f2b6a1c07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("watermark", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "stream", name="uq_sync_state_provider_stream"),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
