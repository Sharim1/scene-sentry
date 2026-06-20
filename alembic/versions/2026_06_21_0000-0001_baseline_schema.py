"""baseline schema

Snapshots the schema as it existed under the legacy ``Base.metadata.create_all()``
+ hand-rolled ``_run_migrations()`` bootstrap, so that Alembic can take over as
the single source of schema truth.

Because every model already encodes the columns/types/constraints that the old
``_run_migrations()`` patched in by hand (``users.timezone``,
``reminders.scheduled_time`` as TIMESTAMPTZ, and ``notifications.reminder_id``
ON DELETE SET NULL), recreating the metadata here is faithful to production.

Existing databases that were created by the legacy path already have these
tables; they are adopted via ``alembic stamp head`` rather than re-running this
migration (see ``app.database.init_db``).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-21 00:00:00.000000

"""

from collections.abc import Sequence

# Importing the models package registers every live table on Base.metadata.
import app.models  # noqa: F401  (side-effecting import)
from alembic import op
from app.database import Base

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
