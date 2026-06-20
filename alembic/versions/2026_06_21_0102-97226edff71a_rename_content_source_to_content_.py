"""rename content.source to content.provider

Revision ID: 97226edff71a
Revises: 0001_baseline
Create Date: 2026-06-21 01:02:54.802300

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "97226edff71a"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename, preserving data (batch mode: RENAME COLUMN on Postgres,
    # table-copy on SQLite).
    with op.batch_alter_table("content") as batch_op:
        batch_op.alter_column("source", new_column_name="provider")


def downgrade() -> None:
    with op.batch_alter_table("content") as batch_op:
        batch_op.alter_column("provider", new_column_name="source")
