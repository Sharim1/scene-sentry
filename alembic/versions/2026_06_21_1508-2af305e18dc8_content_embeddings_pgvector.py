"""content embeddings pgvector

Revision ID: 2af305e18dc8
Revises: 97226edff71a
Create Date: 2026-06-21 15:08:47.587182

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2af305e18dc8"
down_revision: str | None = "97226edff71a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:
            raise RuntimeError(
                "PostgreSQL requires the pgvector extension for content embeddings (SCE-33), "
                "but it is not installed on this server. Fix options:\n"
                "  • Docker (recommended): docker compose up -d postgres\n"
                "    then set DATABASE_URL=postgresql://scenesentry:scenesentry@localhost:5433/scenesentry\n"
                "  • Homebrew: brew install pgvector (must match your Postgres major version)\n"
                "  • Quick local dev without similarity search: DATABASE_URL=sqlite:///scenesentry.db"
            ) from exc
    op.add_column("content", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
    op.add_column("content", sa.Column("embedding_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "content",
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    if is_postgres:
        op.create_index(
            "ix_content_embedding_hnsw",
            "content",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_content_embedding_hnsw", table_name="content")
    op.drop_column("content", "embedding_updated_at")
    op.drop_column("content", "embedding_hash")
    op.drop_column("content", "embedding")
    # Intentionally do NOT drop the vector extension (other objects may use it).
