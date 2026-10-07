"""Content embedding service — build text, call Gemini (injected), refresh job logic (SCE-33)."""

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models.content import Content
from app.repositories.embedding_repo import EmbeddingRepository

logger = logging.getLogger(__name__)


def build_embedding_text(content: Content) -> str:
    """Compose the canonical text that represents a Content item for embedding.

    Deterministic: the same field values always yield the same string.
    """
    genres: list[str] = []
    if content.genres:
        try:
            parsed = json.loads(content.genres)
            if isinstance(parsed, list):
                genres = [str(g) for g in parsed]
        except (ValueError, TypeError):
            genres = []

    parts = [
        f"Title: {content.title}",
        f"Type: {content.content_type}",
    ]
    if genres:
        parts.append(f"Genres: {', '.join(genres)}")
    if content.description:
        parts.append(f"Overview: {content.description}")
    return "\n".join(parts)


def embedding_hash(text: str) -> str:
    """Stable sha256 hex digest of the embedding-input text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingService:
    def __init__(self, db: Session, embedder=None):
        self.db = db
        self.repo = EmbeddingRepository(db)
        self._embedder = embedder

    @property
    def embedder(self):
        """Return a GoogleGenerativeAIEmbeddings, created lazily. None if no API key."""
        if self._embedder is not None:
            return self._embedder
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY not set; embedding job is a no-op")
            return None
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self._embedder = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.gemini_api_key,
            task_type="RETRIEVAL_DOCUMENT",
        )
        return self._embedder

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (uses RETRIEVAL_QUERY task type if available)."""
        return self.embedder.embed_query(text)

    def refresh_embeddings(self, batch_size: int | None = None) -> int:
        """Compute embeddings for Content needing one. Idempotent. Returns count embedded."""
        if not settings.embedding_enabled:
            return 0
        batch_size = batch_size or settings.embedding_batch_size
        embedder = self.embedder
        if embedder is None:
            return 0

        candidates: list[Content] = self.repo.get_embedding_candidates(limit=batch_size)
        if not candidates:
            return 0

        texts = [build_embedding_text(c) for c in candidates]
        vectors = embedder.embed_documents(texts)

        embedded = 0
        for content, text, vector in zip(candidates, texts, vectors, strict=True):
            self.repo.set_embedding(content, vector, embedding_hash(text))
            embedded += 1
        self.db.commit()
        logger.info("Embedded %d content items", embedded)
        return embedded
