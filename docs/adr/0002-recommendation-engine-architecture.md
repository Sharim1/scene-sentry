# ADR-0002: Recommendation Engine — Two-Stage Retrieve→Rerank, Embeddings-First

**Status:** Accepted
**Date:** 2026-06-20
**Deciders:** @sharimpervez
**Related:** PRD [Personalized Discovery & Recommendations](../prd/personalized-discovery-and-recommendations.md); supersedes the heuristic in SCE-21; revives the model SCE-6 would delete.

---

## Context

Scene Sentry's only personalization today is **Ranking** (`UserContentRank`), produced by a LangGraph agent (`app/agents/graph.py`) whose first node, `build_taste_profile`, counts genres across **all** of a user's **Library Items** with no status filter. Two problems:

1. **Cold start.** Casual users arrive with an empty Library. A genre-counter over an empty Library produces nothing, so the first session — the one that decides retention — has no usable recommendations.
2. **Shallow, biased signal.** Every Library Item counts equally regardless of **Watch Status** (a `maybe` skews taste as much as a loved, completed title), and there is no notion of *why* a user liked something, nor any use of **cast/crew** (SCE-21).

We need a recommendation approach that (a) works from the first session via onboarding data, (b) uses rich content signals including cast/crew, (c) explains itself, and (d) is a "build once" decision the team won't have to re-architect.

We evaluated where the field actually is in 2026: the production default is multi-stage **retrieve → rerank**; LLMs are used as embedding/feature generators and rerankers, not as live item generators; and for small catalogs with severe cold-start and rich metadata, semantic/embedding retrieval beats collaborative filtering until interaction volume exists.

## Decision

**Commit to a two-stage, multi-source retrieve→rerank architecture. Start with a single embedding-based retrieval source (Gemini embeddings) plus Gemini rerank/explain. Add LightFM as a second, collaborative retrieval source later, once interaction volume justifies it.**

The durable commitment is the **architecture**, not a single algorithm. Retrieval sources are pluggable; the ranker blends them.

### Stage 1 — Candidate retrieval (cold-start-safe)

- Represent each **Content** item as an **embedding** built from its metadata: title + description + genres + **cast/crew** (ADR-0003) + content type.
- Represent the user's **Taste Profile** as an aggregate of the embeddings of the things they actually liked (onboarding swipes, completed + highly-rated items), with **signal weighting** (below).
- Retrieve nearest-neighbour candidates by similarity. This needs **zero interaction data** — a brand-new user who completed the 60-second onboarding gets good candidates immediately.
- **Vector storage/index: `pgvector` with HNSW, in the existing PostgreSQL** — not a dedicated vector store. At our scale (catalog in the thousands; well under pgvector's ~10M-vector comfort ceiling) this keeps us single-database and, critically, lets candidate retrieval combine vector similarity with relational filters (exclude already-in-Library, filter by type/availability) in one SQL query. Aligns with ADR-001's low-infra stance. A dedicated store is only warranted above ~50M vectors / very high sustained QPS — revisit then.

### Stage 2 — Rerank + explain

- Gemini reranks the small candidate shortlist (~top N) and writes the human-readable "why you'll like this," reusing the existing LLM investment. The LLM never runs over the full Catalog (latency/cost).

### Signal weighting (resolves SCE-21's open questions)

| Source | Weight |
|---|---|
| `completed` + high rating | Highest positive |
| `completed` / `watching` | Positive |
| Onboarding "swipe right" (+ "why" tag boosts cast/story/vibe features) | Positive |
| `planned` | Low / neutral |
| `maybe` | Neutral (does **not** materially shape taste) |
| `dropped` | **Negative** signal |

The "why I liked it" tags (Cast · Story · Vibe/Genre · Director) reweight which item features dominate the user's profile.

### Retraining / serving

- Embeddings for Catalog Content are computed on ingestion/**Enrichment** and refreshed when metadata changes.
- Recommendation generation runs as a **Scheduled Job** (Celery Beat) — never user-triggered (respects ADR "Remove manual Tasks in favor of Scheduled Jobs" and SCE-31). Scores are cached/persisted; new signals take effect at the next run.

### Data model

- **`UserContentRank` (Ranking)** stays: a score + reasoning for Catalog Content against a Taste Profile.
- **`Recommendation` revived (supersedes SCE-6 deletion):** agent-discovered candidates, possibly with external `source_urls`, `dismissed`/`saved_to_library` state. Distinct from Ranking. `CONTEXT.md` glossary must be updated to define both (it currently marks "Recommendation" as a deprecated synonym).

## Alternatives Considered

### LightFM-first (the original instinct)
- **Pros:** single hybrid model handling collaborative + content signals; proven; good metadata cold-start.
- **Cons:** its core strength (collaborative signal) needs interaction **volume** we won't have at launch; CPU-only Cython dependency; quietly maintained. Leaning on CF at launch optimizes for data we don't have.
- **Rejected as the starting point**, but explicitly retained as the **post-launch second retrieval source** — the architecture is designed to add it without rework.

### LLM-as-recommender (generate items directly in the request path)
- **Pros:** rich reasoning, conversational.
- **Cons:** slow, expensive, hallucination-prone, hard to evaluate; industry consensus is "augment, not replace."
- **Rejected** for the hot path; the LLM stays at the rerank/explain step over a small candidate set.

### Two-tower / generative (Semantic IDs, HSTU)
- **Pros:** state-of-the-art at scale.
- **Cons:** massive overkill for our catalog/user scale; heavy infra.
- **Rejected** as premature.

### Patch the existing heuristic (SCE-21 as written)
- **Rejected:** tuning a genre-counter we are about to replace is throwaway work. Its questions are absorbed into the signal-weighting table above.

## Consequences

**Easier:** good first-session recommendations with no Library; cast/crew-aware, explainable, cross-service discovery; adding collaborative filtering later is a plug-in, not a rewrite.

**Harder / new:** introduces an embedding step and a similarity index (a new dependency — to be confirmed per PRD boundaries); embeddings must be refreshed on metadata change; recommendation quality now depends on onboarding quality and embedding inputs (cast/crew, ADR-0003).

**To revisit:** the precise numeric signal weights after observing real behavior; the trigger to introduce the LightFM source (interaction-volume threshold); migrating off `pgvector` to a dedicated vector store only if the catalog grows past ~50M vectors or QPS demands it.
