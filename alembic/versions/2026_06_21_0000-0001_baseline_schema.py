"""baseline schema

Frozen, point-in-time snapshot of the schema as it existed when Alembic was
introduced (the pre-Alembic ``create_all`` + ``_run_migrations()`` state). This
is deliberately explicit (not ``Base.metadata.create_all``) so that later
migrations which alter these tables apply cleanly on a fresh ``upgrade head``.

Existing databases created by the legacy bootstrap are adopted by stamping this
revision rather than re-running it (see ``app.database.init_db``).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-21 00:58:45.495770

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("genres", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=50), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", sa.String(length=20), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("tvmaze_id", sa.Integer(), nullable=True),
        sa.Column("isbn", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("poster_url", sa.String(length=500), nullable=True),
        sa.Column("backdrop_url", sa.String(length=500), nullable=True),
        sa.Column("trailer_url", sa.String(length=500), nullable=True),
        sa.Column("release_date", sa.String(length=20), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("director", sa.String(length=200), nullable=True),
        sa.Column("budget", sa.Integer(), nullable=True),
        sa.Column("seasons", sa.Integer(), nullable=True),
        sa.Column("episodes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("network", sa.String(length=100), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("country", sa.String(length=50), nullable=True),
        sa.Column("is_adaptation", sa.Boolean(), nullable=True),
        sa.Column("adapted_from_id", sa.Integer(), nullable=True),
        sa.Column("adaptation_status", sa.String(length=50), nullable=True),
        sa.Column("next_episode_date", sa.DateTime(), nullable=True),
        sa.Column("premiere_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("content", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_content_content_type"), ["content_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_content_imdb_id"), ["imdb_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_content_title"), ["title"], unique=False)
        batch_op.create_index(batch_op.f("ix_content_tmdb_id"), ["tmdb_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_content_tvdb_id"), ["tvdb_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_content_tvmaze_id"), ["tvmaze_id"], unique=False)

    op.create_table(
        "discovery_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("last_page", sa.Integer(), nullable=False),
        sa.Column("total_items_fetched", sa.Integer(), nullable=False),
        sa.Column("fully_synced", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "content_type", name="uq_provider_content_type"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clerk_id", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preferred_genres", sa.Text(), nullable=True),
        sa.Column("search_api_preference", sa.String(length=20), nullable=True),
        sa.Column("discovery_frequency", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=50), nullable=True),
        sa.Column("email_notifications", sa.Boolean(), nullable=True),
        sa.Column("gossip_notifications", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_clerk_id"), ["clerk_id"], unique=True)

    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("air_date", sa.String(length=20), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("tvmaze_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["content_id"], ["content.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_id", "season_number", "episode_number", name="uq_content_season_episode"),
    )
    with op.batch_alter_table("episodes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_episodes_content_id"), ["content_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_episodes_tvdb_id"), ["tvdb_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_episodes_tvmaze_id"), ["tvmaze_id"], unique=False)

    op.create_table(
        "gossip",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("preview_text", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_author", sa.String(length=200), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column(
            "tag",
            sa.Enum(
                "EXCLUSIVE",
                "CASTING",
                "PRODUCTION",
                "RUMOR",
                "RENEWAL",
                "CANCELLATION",
                "RELEASE",
                "ADAPTATION",
                "BEHIND_SCENES",
                "INTERVIEW",
                "REVIEW",
                "TRENDING",
                name="gossiptag",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("related_content_id", sa.Integer(), nullable=True),
        sa.Column("mentioned_titles", sa.Text(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("share_count", sa.Integer(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("is_featured", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["related_content_id"],
            ["content.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("gossip", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_gossip_related_content_id"), ["related_content_id"], unique=False)

    op.create_table(
        "library_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("WATCHING", "PLANNED", "COMPLETED", "DROPPED", "MAYBE", name="watchstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("current_season", sa.Integer(), nullable=True),
        sa.Column("current_episode", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("weekly_release", sa.Boolean(), nullable=True),
        sa.Column("next_episode_date", sa.DateTime(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["content.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("library_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_library_items_content_id"), ["content_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_library_items_user_id"), ["user_id"], unique=False)

    op.create_table(
        "user_content_ranks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("rank_score", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["content.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "content_id", name="uq_user_content_rank"),
    )
    with op.batch_alter_table("user_content_ranks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_content_ranks_content_id"), ["content_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_content_ranks_user_id"), ["user_id"], unique=False)

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("library_item_id", sa.Integer(), nullable=True),
        sa.Column("content_id", sa.Integer(), nullable=True),
        sa.Column(
            "reminder_type",
            sa.Enum(
                "WATCH", "READ", "NEXT_EPISODE", "PREMIERE", "FINALE", "RELEASE", name="remindertype", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("scheduled_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=50), nullable=True),
        sa.Column("quality", sa.String(length=50), nullable=True),
        sa.Column("sent", sa.Boolean(), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["content.id"],
        ),
        sa.ForeignKeyConstraint(
            ["library_item_id"],
            ["library_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reminders_content_id"), ["content_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_reminders_library_item_id"), ["library_item_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_reminders_scheduled_time"), ["scheduled_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_reminders_user_id"), ["user_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reminder_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=True),
        sa.Column("emailed", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notifications_is_read"), ["is_read"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_reminder_id"), ["reminder_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_user_id"), ["user_id"], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notifications_user_id"))
        batch_op.drop_index(batch_op.f("ix_notifications_reminder_id"))
        batch_op.drop_index(batch_op.f("ix_notifications_is_read"))

    op.drop_table("notifications")
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reminders_user_id"))
        batch_op.drop_index(batch_op.f("ix_reminders_scheduled_time"))
        batch_op.drop_index(batch_op.f("ix_reminders_library_item_id"))
        batch_op.drop_index(batch_op.f("ix_reminders_content_id"))

    op.drop_table("reminders")
    with op.batch_alter_table("user_content_ranks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_content_ranks_user_id"))
        batch_op.drop_index(batch_op.f("ix_user_content_ranks_content_id"))

    op.drop_table("user_content_ranks")
    with op.batch_alter_table("library_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_library_items_user_id"))
        batch_op.drop_index(batch_op.f("ix_library_items_content_id"))

    op.drop_table("library_items")
    with op.batch_alter_table("gossip", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_gossip_related_content_id"))

    op.drop_table("gossip")
    with op.batch_alter_table("episodes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_episodes_tvmaze_id"))
        batch_op.drop_index(batch_op.f("ix_episodes_tvdb_id"))
        batch_op.drop_index(batch_op.f("ix_episodes_content_id"))

    op.drop_table("episodes")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_clerk_id"))

    op.drop_table("users")
    op.drop_table("discovery_state")
    with op.batch_alter_table("content", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_content_tvmaze_id"))
        batch_op.drop_index(batch_op.f("ix_content_tvdb_id"))
        batch_op.drop_index(batch_op.f("ix_content_tmdb_id"))
        batch_op.drop_index(batch_op.f("ix_content_title"))
        batch_op.drop_index(batch_op.f("ix_content_imdb_id"))
        batch_op.drop_index(batch_op.f("ix_content_content_type"))

    op.drop_table("content")
    # ### end Alembic commands ###
