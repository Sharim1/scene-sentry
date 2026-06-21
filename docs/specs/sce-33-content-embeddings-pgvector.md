# Spec: SCE-33 — Content Embeddings + pgvector Similarity Index

**Linear:** [SCE-33](https://linear.app/scene-sentry/issue/SCE-33) · **Parent:** SCE-32 (PRD: Personalized Discovery & Recommendations) · **ADR:** [0002 Recommendation Engine](../adr/0002-recommendation-engine-architecture.md)
**Status:** Ready for implementation
**Audience:** This spec is written to be implemented step-by-step by an LLM. Every file path, column name, function signature, and SQL snippet is given explicitly. Do not improvise names or skip the verification step on any task.

---

## Objective

Build the **cold-start-safe retrieval foundation** for the recommendation engine.

Store a semantic **embedding** for each `Content` row in PostgreSQL using the `pgvector` extension (HNSW index). A **Scheduled Job** (Celery Beat) computes and refreshes these embeddings from existing Content metadata (title + content type + genres + description). Expose a repository method that, given a query embedding, returns the nearest-neighbour `Content` rows — combinable with ordinary SQL filters (exclude an id, filter by content type) in a single query.

**This slice is intentionally thin but complete and demoable on its own:** given a Content item, return the most similar Content. **There is NO user-facing Ranking, NO Taste Profile, and NO Gemini reranking in this slice** — those are later slices (SCE-34/35/36). Do not build them here.

### Success criteria (testable)

1. `pgvector` extension is enabled and `content` has `embedding vector(768)`, `embedding_hash`, and `embedding_updated_at` columns, added via an Alembic migration with an HNSW cosine index on `embedding`.
2. A Celery Beat task `embedding_refresh_task` computes embeddings for Content with a missing or invalidated embedding, in batches, **idempotently** (a second run with no content changes makes zero embedding API calls and zero DB writes to the embedding column). It is never user-triggered.
3. `EmbeddingRepository.find_similar(embedding, limit, exclude_id, content_type)` returns the top-N most-similar Content, honouring the relational filters, in one SQL query.
4. Tests pass: SQLite unit tests cover input-text building, hashing, candidate selection, staleness invalidation, and job idempotency (Gemini mocked); a Postgres+pgvector integration test proves `find_similar` returns plausible neighbours and auto-skips when no test Postgres is configured.

---

## Decisions already made (do not re-litigate)

These come from ADR-0002 and the spec author. Implement them as written.

| Decision | Value | Why |
|---|---|---|
| Vector store | `pgvector` in the existing Postgres (not a dedicated vector DB) | ADR-0002; lets vector + relational filters run in one query; low-infra |
| Index | HNSW, `vector_cosine_ops`, `m=16, ef_construction=64` | ADR-0002; good recall/latency at our catalog scale |
| Embedding provider | Gemini via `langchain-google-genai` (already a dependency) | Reuses existing Gemini investment |
| Embedding model | `models/text-embedding-004` | Fixed 768 dims, stable, supports `task_type` |
| Embedding dimension | **768** | Under pgvector's 2000-dim HNSW ceiling; storage-light |
| Distance metric | **Cosine** (`<=>`) | text-embedding-004 outputs are suited to cosine/semantic similarity |
| Staleness detection | `embedding_hash` = sha256 of the embedding-input text | Cheap, deterministic, idempotent; avoids the `updated_at` self-trigger trap |
| Scheduling | Celery Beat Scheduled Job, never user-triggered | ADR "Remove manual Tasks in favor of Scheduled Jobs" |
| Dependency on SCE-5 | **None.** This slice only ADDS new columns; it does not read or rename `content.source`. | Sidesteps the unmerged SCE-5 rename |

---

## Tech stack

- Python 3.11+, FastAPI, SQLAlchemy 2.x (sync sessions)
- PostgreSQL + **pgvector** extension (prod & dev); SQLite only for unit tests
- Alembic for migrations (baseline migration already exists)
- Celery + Redis (Celery Beat for periodic jobs)
- `langchain-google-genai` (`GoogleGenerativeAIEmbeddings`) — already in `pyproject.toml`
- **New dependency to add:** `pgvector>=0.3.6` (Python package; provides `pgvector.sqlalchemy.Vector`). This is pre-approved by ADR-0002 (the `pgvector` decision). Add it to `[project.dependencies]` in `pyproject.toml` and run `uv lock`.

---

## Commands

```bash
# Install / sync deps (after adding pgvector to pyproject)
uv sync

# Generate the migration is NOT autogenerate — write it by hand (see Task 3). Then apply:
uv run alembic upgrade head

# Run all unit tests (SQLite; integration tests auto-skip)
uv run pytest

# Run including the Postgres integration test (requires a pgvector-enabled Postgres)
TEST_DATABASE_URL="postgresql://scenesentry:scenesentry@localhost:5432/scenesentry_test" uv run pytest -m integration

# Lint + format (must pass before commit)
uv run ruff check . --fix
uv run ruff format .

# Run the embedding job once locally (manual smoke test, not a user trigger)
uv run celery -A app.celery_app worker --pool=solo --loglevel=info
# then in a python shell: from app.tasks.periodic import embedding_refresh_task; embedding_refresh_task.delay()
```

---

## Project structure — files to create / modify

```
app/
  models/content.py                      # MODIFY  — add embedding columns
  repositories/embedding_repo.py         # CREATE  — candidate selection + find_similar
  repositories/content_repo.py           # MODIFY  — null embedding_hash on relevant field changes
  services/embedding_service.py          # CREATE  — build text, call Gemini (injected), refresh job logic
  tasks/periodic.py                      # MODIFY  — add embedding_refresh_task
  celery_app.py                          # MODIFY  — add beat schedule entry
  config.py                              # MODIFY  — add embedding_* settings
  routes/api.py                          # MODIFY  — add GET /api/content/{id}/similar demo endpoint
alembic/versions/
  2026_06_22_XXXX-0002_content_embeddings.py   # CREATE — migration
tests/
  conftest.py                            # MODIFY  — add FakeEmbedder + postgres integration fixtures
  test_embedding_service.py              # CREATE  — SQLite unit tests
  test_embedding_repo.py                 # CREATE  — SQLite unit tests (selection/staleness)
  test_embedding_similarity_integration.py # CREATE — Postgres-only, @pytest.mark.integration
.github/workflows/ci.yml                 # MODIFY  — add pgvector Postgres service to the test job
pyproject.toml                           # MODIFY  — add pgvector dep + register "integration" marker
docs/CHANGELOG.md                        # leave for the PR step
```

> **Branch off the latest `main`.** SCE-5 (`content.source`→`provider`) is merged on `main`, and the Alembic baseline lives there too. Do NOT branch from the `sce-37` branch (it forked from an older `main` that predates SCE-5).

---

## Code style

Match the existing codebase exactly. Reference: `app/repositories/content_repo.py`, `app/services/content_discovery.py`.

- Type hints on every function signature; use `X | None`, `list[X]`, `dict[str, X]` (PEP 604/585), not `Optional`/`List`.
- Module-level `logger = logging.getLogger(__name__)`; log with `%`-style lazy args (`logger.info("Embedded %d items", n)`).
- Repositories take a `db: Session` in `__init__` and only do data access. Services hold business logic. Tasks are thin and delegate to services.
- Timezone-aware UTC datetimes via the existing `utc_now()` helper pattern.
- Keep functions small; no function should exceed ~40 lines.

Example of the target style (a repository method):

```python
def get_by_id(self, content_id: int) -> Content | None:
    return self.db.query(Content).filter(Content.id == content_id).first()
```

---

## Data model changes

### `app/models/content.py`

Add at the top, near the other imports:

```python
from pgvector.sqlalchemy import Vector
```

Add a module-level constant (used by the model and the migration — keep them in sync):

```python
EMBEDDING_DIM = 768
```

Add these columns to the `Content` class, after the `genres` column block:

```python
    # Semantic embedding for similarity retrieval (SCE-33). Postgres/pgvector only.
    # On SQLite (tests) the column is created but vector operations are unavailable.
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    # sha256 of the embedding-input text; NULL means "needs (re)embedding".
    embedding_hash = Column(String(64), nullable=True)
    embedding_updated_at = Column(DateTime(timezone=True), nullable=True)
```

> **Note for the implementer:** importing `pgvector.sqlalchemy.Vector` does NOT require Postgres — it is a pure Python type. `Base.metadata.create_all` on SQLite will create the column with a `VECTOR(768)` type string, which SQLite accepts (it just can't run vector operators). **Verify** this by running the existing test suite after the model change — `tests/conftest.py` calls `create_all` on SQLite; if it errors, stop and report.

---

## Migration

### New migration under `alembic/versions/`

**Scaffold it with the CLI so the revision id and `down_revision` are wired correctly**, then fill in the body. Do NOT hand-pick the revision id, and do NOT use `--autogenerate` (it cannot emit the extension or the HNSW index):

```bash
uv run alembic revision -m "content embeddings pgvector"
```

This creates a new file whose `down_revision` is auto-set to the current head. **Confirm the chain before editing:** the current head is `97226edff71a` (the SCE-5 rename), which itself chains off `0001_baseline`. So the generated file must have `down_revision = "97226edff71a"`. Verify with `uv run alembic heads` (expect a single head). Then replace the generated `upgrade`/`downgrade` bodies with the code below (keep the auto-generated `revision`/`down_revision` lines as scaffolded — do not overwrite them with literals):

```python
"""content embeddings pgvector

Revises: 97226edff71a   # the SCE-5 rename head — auto-filled by `alembic revision`
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision / down_revision: leave exactly as the CLI scaffolded them.
# down_revision must be "97226edff71a" (the current head).

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("content", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
    op.add_column("content", sa.Column("embedding_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "content",
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_content_embedding_hnsw",
        "content",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_content_embedding_hnsw", table_name="content")
    op.drop_column("content", "embedding_updated_at")
    op.drop_column("content", "embedding_hash")
    op.drop_column("content", "embedding")
    # Intentionally do NOT drop the vector extension (other objects may use it).
```

---

## Embedding input text (deterministic) + hash

These two pure functions live in `app/services/embedding_service.py`. They must be deterministic — same Content always produces the same text and hash.

```python
import hashlib
import json

from app.models.content import Content


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
```

---

## Embedding service

### `app/services/embedding_service.py`

The service builds input text, calls Gemini, and runs the refresh loop. **The embedder is injected** so tests can pass a fake (never hit the network in tests).

```python
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models.content import Content
from app.repositories.embedding_repo import EmbeddingRepository
# build_embedding_text / embedding_hash defined above in this module

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, db: Session, embedder=None):
        self.db = db
        self.repo = EmbeddingRepository(db)
        self._embedder = embedder  # lazily created if None (see embedder property)

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
            model=settings.embedding_model,           # "models/text-embedding-004"
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
        vectors = embedder.embed_documents(texts)  # list[list[float]], len == len(texts)

        embedded = 0
        for content, text, vector in zip(candidates, texts, vectors, strict=True):
            self.repo.set_embedding(content, vector, embedding_hash(text))
            embedded += 1
        self.db.commit()
        logger.info("Embedded %d content items", embedded)
        return embedded
```

> **Idempotency contract:** `get_embedding_candidates` only returns rows where `embedding IS NULL OR embedding_hash IS NULL`. After `set_embedding`, both are populated, so the next run returns no candidates → zero API calls. Tests assert this.

---

## Embedding repository

### `app/repositories/embedding_repo.py`

Isolates all pgvector-specific access. `find_similar` is the deliverable query.

```python
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
        return (
            query.order_by(Content.embedding.cosine_distance(embedding))
            .limit(limit)
            .all()
        )
```

### Staleness trigger — `app/repositories/content_repo.py`

When enrichment/merge fills an embedding-input field (description, genres), the stored embedding becomes stale. Invalidate it by nulling `embedding_hash` so the next job run re-embeds. In `ContentRepository._merge_into`, set a flag when a relevant field changes and null the hash at the end:

```python
    def _merge_into(self, content: Content, nc: NormalizedContent) -> None:
        embedding_input_changed = False
        if nc.description and not content.description:
            content.description = nc.description[:500]
            embedding_input_changed = True
        # ... existing merges ...
        if nc.genres and not content.genres:
            content.genres = json.dumps(nc.genres)
            embedding_input_changed = True
        # ... rest of existing merges unchanged ...
        content.updated_at = datetime.now(UTC)
        if embedding_input_changed:
            content.embedding_hash = None  # mark for re-embedding (SCE-33)
```

> Only `title`, `content_type`, `genres`, `description` feed `build_embedding_text`. Title/content_type don't change in `_merge_into`, so only the `description` and `genres` branches set the flag. Do not null the `embedding` vector itself — keep the stale-but-usable vector until the refresh runs (availability).

---

## Celery task + schedule

### `app/tasks/periodic.py` — add

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def embedding_refresh_task(self):
    try:
        from app.services.embedding_service import EmbeddingService

        with db_session() as db:
            svc = EmbeddingService(db)
            embedded = svc.refresh_embeddings()
            if embedded:
                logger.info("Embedding refresh: %d items", embedded)
            return embedded
    except Exception as exc:
        logger.exception("embedding_refresh_task failed")
        raise self.retry(exc=exc)
```

### `app/celery_app.py` — add to `beat_schedule`

```python
        "content-embedding": {
            "task": "app.tasks.periodic.embedding_refresh_task",
            "schedule": timedelta(minutes=settings.embedding_interval_minutes),
        },
```

---

## Config additions

### `app/config.py` — add to the `Settings` class

```python
    # Embeddings (SCE-33)
    embedding_enabled: bool = True
    embedding_model: str = "models/text-embedding-004"
    embedding_dim: int = 768
    embedding_interval_minutes: int = 30
    embedding_batch_size: int = 100
```

---

## Demo endpoint (internal verification surface)

A thin JSON route so the similarity feature is clickable. Add it to `app/routes/api.py` (router already has `prefix="/api"`). Follow the file's existing conventions: `DbDep` / `RequireAuthDep` from `app.dependencies`, lazy repo imports inside the function, a `pydantic.BaseModel` `response_model`. **Every symbol gets a docstring** that states what it is and that it is the SCE-33 *embeddings demo*, not the user-facing recommendations feature (SCE-34).

```python
from pydantic import BaseModel  # already imported in api.py


class SimilarContentItem(BaseModel):
    """One nearest-neighbour result in the SCE-33 similarity demo response."""

    id: int
    title: str
    content_type: str
    poster_url: str | None = None


class SimilarContentResponse(BaseModel):
    """Response body for the internal SCE-33 similarity demo endpoint.

    Lists catalog Content most semantically similar to a given Content, using the
    precomputed pgvector embeddings built in SCE-33. This is an internal demo /
    verification surface for the embeddings foundation — it is NOT the user-facing
    personalized recommendations feature, which is built in SCE-34.
    """

    source_id: int
    results: list[SimilarContentItem]


@router.get("/content/{content_id}/similar", response_model=SimilarContentResponse)
def get_similar_content(
    content_id: int,
    db: DbDep,
    user: RequireAuthDep,
    limit: int = Query(10, ge=1, le=50),
) -> SimilarContentResponse:
    """Return the Content most similar to a given Content (SCE-33 demo endpoint).

    Internal verification surface for the embeddings + pgvector foundation. Uses the
    target row's PRECOMPUTED embedding, so it makes NO embedding API call and is safe
    in the request path. Returns an empty list when the target has no embedding yet
    (the Scheduled Job has not processed it). This is NOT the personalized
    recommendations endpoint — see SCE-34.
    """
    from app.repositories.content_repo import ContentRepository
    from app.repositories.embedding_repo import EmbeddingRepository

    content = ContentRepository(db).get_by_id(content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if content.embedding is None:
        return SimilarContentResponse(source_id=content_id, results=[])

    neighbours = EmbeddingRepository(db).find_similar(
        content.embedding, limit=limit, exclude_id=content_id
    )
    return SimilarContentResponse(
        source_id=content_id,
        results=[
            SimilarContentItem(
                id=c.id,
                title=c.title,
                content_type=c.content_type,
                poster_url=c.poster_url,
            )
            for c in neighbours
        ],
    )
```

> **Route ordering note:** `content.py` registers a catch-all `GET /{content_id}` (single segment). This new route is `/api/content/{content_id}/similar` — different prefix and two segments — so there is no collision.

---

## Testing strategy

Two tiers. **Gemini is mocked in every test — no test may hit the network.**

### Tier 1 — SQLite unit tests (run always, via existing `db_session` fixture)

Add a deterministic fake embedder to `tests/conftest.py`:

```python
@pytest.fixture()
def fake_embedder():
    """Deterministic stand-in for GoogleGenerativeAIEmbeddings — no network."""
    class FakeEmbedder:
        def __init__(self):
            self.embed_calls = 0

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.embed_calls += 1
            # Deterministic 768-d vector seeded from the text length & first char.
            return [self._vec(t) for t in texts]

        def embed_query(self, text: str) -> list[float]:
            return self._vec(text)

        @staticmethod
        def _vec(text: str) -> list[float]:
            seed = (len(text) % 7) + 1
            base = [float((i * seed) % 5) for i in range(768)]
            return base

    return FakeEmbedder()
```

`tests/test_embedding_service.py` must cover:

- `build_embedding_text` is deterministic and includes title, type, genres (parsed from JSON), and overview; omits genres/overview when absent.
- `embedding_hash` is stable and changes when input text changes.
- `refresh_embeddings`: with N candidate rows + `fake_embedder`, embeds all N, sets `embedding`, `embedding_hash`, `embedding_updated_at`, commits.
- **Idempotency:** calling `refresh_embeddings` a second time returns `0` and `fake_embedder.embed_calls` does NOT increase.
- No-op when `settings.embedding_enabled = False` and when `embedder is None` (no API key).

`tests/test_embedding_repo.py` must cover:

- `get_embedding_candidates` returns rows with `embedding IS NULL OR embedding_hash IS NULL`, respects `limit`, excludes fully-embedded rows.
- `_merge_into` nulls `embedding_hash` when description/genres get filled (staleness trigger), and does NOT null it when only an unrelated field (e.g. `poster_url`) changes.

> Inject the fake: `EmbeddingService(db_session, embedder=fake_embedder)`.

### Tier 2 — Postgres integration test (auto-skips without Postgres)

`tests/test_embedding_similarity_integration.py`, marked `@pytest.mark.integration`. Use a session-scoped fixture that builds an engine from `TEST_DATABASE_URL`, runs `CREATE EXTENSION IF NOT EXISTS vector`, `create_all`, and **skips the whole module** if the env var is unset or the connection fails:

```python
import os
import pytest

pytestmark = pytest.mark.integration

TEST_DB = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def pg_session():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set; skipping pgvector integration test")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    engine = create_engine(TEST_DB)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres/pgvector unavailable: {exc}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
```

The test itself: insert three Content rows with hand-chosen 768-d vectors where two are close (e.g. two action movies) and one is far (a documentary); assert `find_similar(query_vec, exclude_id=action1.id)` returns `action2` before `documentary`, and that `content_type`/`exclude_id` filters are honoured.

> **This test runs in CI.** Per decision #1, the CI `test` job gets a pgvector-enabled Postgres service and sets `TEST_DATABASE_URL`, so this integration test executes on every push — it is not skipped in CI. It still auto-skips on a plain local `uv run pytest` (no `TEST_DATABASE_URL`). See Task 11.

### `pyproject.toml` — register the marker

```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests requiring external services (e.g. Postgres+pgvector)",
]
```

---

## Boundaries

- **Always:**
  - Run the embedding job as a Celery Beat Scheduled Job; inject the embedder/repositories into the service for testability; mock Gemini in tests.
  - Keep `find_similar` a single query that combines vector ordering with relational filters.
  - Run `ruff check --fix` and `ruff format` before every commit; keep commits small and Conventional-Commit formatted (`feat(embeddings): ...`).
- **Ask first:**
  - Adding any dependency beyond `pgvector` (e.g. `testcontainers`). `pgvector` itself is ADR-approved.
  - Changing the embedding dimension, model, or distance metric.
  - Any change to `content.source`/the SCE-5 rename — out of scope here.
- **Never:**
  - Make the embedding job user-triggerable or add SSE/progress (removed in SCE-31).
  - Call an LLM in the `find_similar` hot path or over the full Catalog.
  - Hit the real Gemini API in tests, or commit an API key.
  - Build Taste Profiles, UserContentRank, or Gemini reranking in this slice (later issues).

---

## Implementation tasks (ordered by dependency)

Implement one task at a time. After each, run the listed verification before moving on. Follow the `test-driven-development` skill: write the test first where a unit test is listed.

- [ ] **Task 1 — Add the `pgvector` dependency.**
  - Acceptance: `pgvector>=0.3.6` in `pyproject.toml` `[project.dependencies]`; `uv lock` updated; `from pgvector.sqlalchemy import Vector` imports in a `uv run python` shell.
  - Verify: `uv sync && uv run python -c "from pgvector.sqlalchemy import Vector; print('ok')"`
  - Files: `pyproject.toml`, `uv.lock`

- [ ] **Task 2 — Add embedding columns to the model.**
  - Acceptance: `Content` has `embedding` (`Vector(768)`), `embedding_hash` (`String(64)`), `embedding_updated_at` (tz-aware), plus `EMBEDDING_DIM = 768`.
  - Verify: `uv run pytest tests/test_health.py tests/test_config.py` passes (proves `create_all` on SQLite still works with the new column).
  - Files: `app/models/content.py`

- [ ] **Task 3 — Write the Alembic migration.**
  - Acceptance: a new migration scaffolded via `uv run alembic revision -m "content embeddings pgvector"` with `down_revision = "97226edff71a"` (the current head — verify with `uv run alembic heads`); its `upgrade` enables `vector`, adds the three columns, and creates the HNSW cosine index; `downgrade` reverses the columns + index (not the extension). `uv run alembic heads` still shows a single head afterwards.
  - Verify (needs local Postgres): `uv run alembic upgrade head` then `uv run alembic downgrade -1` then `uv run alembic upgrade head` — all succeed; `\d content` in psql shows the columns + `ix_content_embedding_hnsw`.
  - Files: the new `alembic/versions/2026_06_22_XXXX_*.py`

- [ ] **Task 4 — Config settings.**
  - Acceptance: the five `embedding_*` settings exist with the defaults above.
  - Verify: `uv run python -c "from app.config import settings; print(settings.embedding_model, settings.embedding_dim)"`
  - Files: `app/config.py`

- [ ] **Task 5 — Embedding repository (+ unit tests first).**
  - Acceptance: `EmbeddingRepository` with `get_embedding_candidates`, `set_embedding`, `find_similar` as specified; `test_embedding_repo.py` covers candidate selection.
  - Verify: `uv run pytest tests/test_embedding_repo.py`
  - Files: `app/repositories/embedding_repo.py`, `tests/test_embedding_repo.py`

- [ ] **Task 6 — Staleness trigger in ContentRepository (+ unit test).**
  - Acceptance: `_merge_into` nulls `embedding_hash` only when description/genres are filled; covered by a test.
  - Verify: `uv run pytest tests/test_embedding_repo.py`
  - Files: `app/repositories/content_repo.py`, `tests/test_embedding_repo.py`

- [ ] **Task 7 — Embedding service (+ unit tests first, with fake embedder).**
  - Acceptance: `build_embedding_text`, `embedding_hash`, `EmbeddingService.refresh_embeddings` / `embed_query` as specified; idempotency + no-op cases tested; `fake_embedder` fixture added to conftest.
  - Verify: `uv run pytest tests/test_embedding_service.py`
  - Files: `app/services/embedding_service.py`, `tests/test_embedding_service.py`, `tests/conftest.py`

- [ ] **Task 8 — Celery task + beat schedule.**
  - Acceptance: `embedding_refresh_task` in `periodic.py`; `content-embedding` entry in `beat_schedule`; task delegates to `EmbeddingService.refresh_embeddings`.
  - Verify: `uv run python -c "from app.celery_app import celery_app; print('content-embedding' in celery_app.conf.beat_schedule)"` prints `True`; add a task test mirroring `tests/test_periodic_tasks.py` (mock `EmbeddingService`).
  - Files: `app/tasks/periodic.py`, `app/celery_app.py`, `tests/test_periodic_tasks.py`

- [ ] **Task 9 — Postgres similarity integration test.**
  - Acceptance: `test_embedding_similarity_integration.py` proves neighbour ordering + filters; auto-skips without `TEST_DATABASE_URL`; `integration` marker registered.
  - Verify: `uv run pytest` (skips) AND `TEST_DATABASE_URL=... uv run pytest -m integration` (passes against pgvector Postgres).
  - Files: `tests/test_embedding_similarity_integration.py`, `pyproject.toml`

- [ ] **Task 10 — Demo endpoint `GET /api/content/{id}/similar` (+ route test).**
  - Acceptance: endpoint added to `app/routes/api.py` exactly as specified, with docstrings on the route + both response models explaining it is the SCE-33 demo surface (not SCE-34 recommendations); uses the stored embedding (no embedding API call); 404 on unknown id; empty `results` when the target has no embedding. A route test (SQLite, via `TestClient`) covers: unknown id → 404, and target-with-no-embedding → empty results. (Ranked-neighbour ordering is covered by the Postgres integration test, not here.)
  - Verify: `uv run pytest tests/test_api_similar.py`
  - Files: `app/routes/api.py`, `tests/test_api_similar.py`

- [ ] **Task 11 — Wire the integration test into CI (pgvector Postgres service).**
  - Acceptance: the `test` job in `.github/workflows/ci.yml` runs a pgvector Postgres as a service container and exports `TEST_DATABASE_URL`, so `pytest` runs the integration test (not skipped) in CI. Existing SQLite unit tests still run in the same job.
  - Add a `services:` block + `TEST_DATABASE_URL` env to the existing `test` job. Use the official pgvector image so the `vector` extension is available:

    ```yaml
      test:
        name: Test
        runs-on: ubuntu-latest
        services:
          postgres:
            image: pgvector/pgvector:pg16
            env:
              POSTGRES_USER: scenesentry
              POSTGRES_PASSWORD: scenesentry
              POSTGRES_DB: scenesentry_test
            ports:
              - 5432:5432
            options: >-
              --health-cmd "pg_isready -U scenesentry"
              --health-interval 10s
              --health-timeout 5s
              --health-retries 5
        env:
          DATABASE_URL: "sqlite:///test.db"          # unit tests keep using SQLite
          TEST_DATABASE_URL: "postgresql://scenesentry:scenesentry@localhost:5432/scenesentry_test"
          SECRET_KEY: "ci-test-key"
          ENV: "development"
        steps:
          # ... existing checkout / setup-uv / setup-python / install steps unchanged ...
          - name: Run tests
            run: pytest --cov --cov-report=term-missing --cov-report=xml -q
          # ... existing coverage upload step unchanged ...
    ```

  - Verify: open a PR; the CI `Test` job log shows the integration test **running (not skipped)** and passing. Locally, `uv run pytest` still passes with the integration test skipped.
  - Files: `.github/workflows/ci.yml`

- [ ] **Task 12 — Full suite + lint, then changelog.**
  - Acceptance: `uv run pytest` green; `uv run ruff check .` and `uv run ruff format --check .` clean. Add a CHANGELOG entry under a new `feat(embeddings)`.
  - Verify: all three commands pass.
  - Files: `CHANGELOG.md`

---

## Decisions log (resolved)

These were open questions during spec review; all are now settled.

1. **Test Postgres in CI — INCLUDED (in scope, Task 11).** The similarity integration test runs in CI against a `pgvector/pgvector:pg16` service container with `TEST_DATABASE_URL` set. It still auto-skips on a plain local `uv run pytest`.
2. **SCE-5 status — RESOLVED, no action.** Verified directly against GitHub: `content.provider` exists on `main` (the rename is merged; the earlier "still `source`" reading was from a stale local `main`). This slice doesn't touch that column regardless. **Branch SCE-33 off the latest `main`.**
3. **Demo endpoint — INCLUDED (Task 10).** Add a thin internal JSON route `GET /api/content/{content_id}/similar` so the feature is clickable/verifiable. It uses the target row's **already-stored embedding** (no Gemini call in the request path — respects the "never call an LLM in the hot path" boundary). Every new symbol it introduces (route, response model, repo call site) carries a docstring stating plainly what it is and that it is an internal demo/verification surface for SCE-33, not the user-facing recommendations feature (that is SCE-34). See "Demo endpoint" below.
4. **Initial backfill command — SKIPPED.** No one-off bulk command. The Scheduled Job fills the catalog gradually at `embedding_batch_size=100` per 30-min run. Revisit only if a fast first backfill is needed for a demo.
```