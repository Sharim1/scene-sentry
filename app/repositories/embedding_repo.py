"""pgvector-specific data access for Content embeddings (SCE-33)."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.content import Content

logger = logging.getLogger(__name__)


class EmbeddingRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_embedding_candidates(self, limit: int = 100) -> list[Content]:
        """Content needing (re)embedding: no embedding yet, or hash invalidated."""
        return (
            self.db.query(Content)
            .filter((Content.embedding.is_(None)) | (Content.embedding_hash.is_(None)))
            .order_by(Content.id)
            .limit(limit)
            .all()
        )

    def set_embedding(self, content: Content, vector: list[float], text_hash: str) -> None:
        """Persist a computed embedding + its hash. Does not commit."""
        content.embedding = vector
        content.embedding_hash = text_hash
        content.embedding_updated_at = datetime.now(UTC)

    def find_similar(
        self,
        embedding: list[float],
        limit: int = 20,
        exclude_id: int | None = None,
        content_type: str | None = None,
    ) -> list[Content]:
        """Return the top-N most cosine-similar Content to `embedding`.

        Combines vector similarity with relational filters in a single query.
        Requires Postgres + pgvector (the `embedding` column + HNSW index).
        """
        query = self.db.query(Content).filter(Content.embedding.is_not(None))
        if exclude_id is not None:
            query = query.filter(Content.id != exclude_id)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.order_by(Content.embedding.cosine_distance(embedding)).limit(limit).all()
