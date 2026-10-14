"""catalog review list

Titles the identity resolver reports as a conflict are parked here with the reason instead
of being guessed, merged or dropped (ADR-0006, issue #83). ``fingerprint`` is unique so a
re-run of the sync does not list the same title twice. New, empty table: no backfill.

BEFORE RUNNING IN PRODUCTION: take a snapshot/backup first.
ROLLBACK: ``alembic downgrade 8d2f4b6a1c93`` drops ``catalog_review`` (only parked entries are lost).

Revision ID: 9e5a3c7b2d18
Revises: 8d2f4b6a1c93
Create Date: 2026-10-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9e5a3c7b2d18"
down_revision: str | None = "8d2f4b6a1c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(30), nullable=True),
        sa.Column("fingerprint", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_catalog_review_fingerprint"),
    )


def downgrade() -> None:
    op.drop_table("catalog_review")
