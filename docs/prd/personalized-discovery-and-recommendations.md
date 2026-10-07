# PRD: Personalized Discovery & Recommendations

**Status:** Draft
**Date:** 2026-06-20
**Author:** @sharimpervez
**Related ADRs:** [0002 Recommendation Engine](../adr/0002-recommendation-engine-architecture.md), [0003 Cast & Crew Data Model](../adr/0003-cast-and-crew-data-model.md), [0004 Release-Date & OTT Sourcing](../adr/0004-release-date-and-ott-sourcing.md), [0005 Frontend Architecture](../adr/0005-frontend-architecture.md)

---

## Problem Statement

A casual viewer opens Scene Sentry with an empty **Library** and immediately hits the "what do I watch tonight?" paralysis that Scene Sentry is supposed to solve. But the only personalization we have — **Ranking** (`UserContentRank`) — is useless until that user has manually built a Library and rated things. The first session, which is the session that decides whether they ever come back, falls flat.

On top of that:

- A user can't tell Scene Sentry *why* they liked something (was it the cast? the story? the vibe?), so the signal we collect is shallow.
- **Cast and crew** — a primary reason many people pick what to watch — are not part of how we match Content.
- Nothing proactively finds *new* Content or **Gossip** a user might like; they have to go looking.
- When a tracked title gets a theatrical or streaming release date, the user has to set a **Reminder** by hand (or misses it).
- Core Library interactions still feel heavier than they should (see SCE-25), which undermines the "open it daily" habit we're targeting.

## Solution

A single, coherent personalized-discovery experience for casual viewers, built so the smart parts work from the very first session.

1. **Taste onboarding (~60s).** A swipe/tap pass over recognizable titles (👍 / 👎 / "seen it"), and for strong positives a one-tap **"why?"** chip (Cast · Story · Vibe/Genre · Director). This seeds a usable **Taste Profile** before the user has any Library.
2. **Two-stage recommendation engine.** Semantic embeddings retrieve candidate **Content** (cold-start-safe, cross-service); Gemini reranks the shortlist and writes the human "why you'll like this." See ADR-0002.
3. **Richer signal capture.** Ratings + all five **Watch Statuses** + the "why I liked it" tags + cast/crew-aware matching all feed the engine, with explicit per-status weighting.
4. **Continuous Discovery agent.** A **Scheduled Job** proactively surfaces new Content and Gossip a user might like, stored as **Recommendations** with reasoning and external source links.
5. **Auto-Reminders.** When a tracked title has a known theatrical or OTT release date, a **Reminder** is created automatically. See ADR-0004.
6. **Instant Library interactions (SCE-25).** No-reload add/remove/status changes and tab switching — a committed launch requirement.

## User Stories

1. As a new user, I want a short, fun onboarding that learns my taste, so that my first recommendations are good without manually building a Library.
2. As a new user, I want to swipe through familiar titles quickly, so that seeding my taste feels effortless, not like data entry.
3. As a new user who marks a title as loved, I want to tap *why* I loved it (cast/story/vibe/director), so that recommendations reflect what actually matters to me.
4. As a returning user, I want one confident "what to watch" suggestion with a reason, so that I don't have to browse an endless grid.
5. As a user, I want recommendations that consider the cast and crew, so that I find work by people I already like.
6. As a user, I want my recommendations explained in plain language, so that I trust them and understand the match.
7. As a user, I want recommendations to span streaming services, not just one, so that discovery isn't locked to a single platform.
8. As a user, I want to set a **Watch Status** of watching, planned, completed, dropped, or maybe, so that my Library reflects reality.
9. As a user, I want to rate a title when I set its status, so that my preference is captured at the natural moment.
10. As a user, I want titles I merely marked "maybe" or "planned" to not distort my taste as much as titles I actually completed and loved (resolves SCE-21).
11. As a user, I want titles I dropped to count as a negative signal, so that I stop being shown similar things.
12. As a user, I want Scene Sentry to proactively find new Content I might like, so that discovery happens even when I'm not searching.
13. As a user, I want proactive **Gossip** about titles and people I follow, so that I stay current on things I care about.
14. As a user, I want to dismiss or save a proactive **Recommendation**, so that the agent learns and my list stays relevant.
15. As a user who tracks an upcoming title, I want a **Reminder** created automatically when its release date is known, so that I don't miss a premiere or OTT drop.
16. As a user, I want to know *where* (theater vs which OTT) and *when* a tracked title releases, so that I can plan to watch it.
17. As a user, I want adding, removing, or restatusing a Library item to update instantly without a full page reload, so that managing my Library feels smooth (SCE-25).
18. As a user, I want to switch Library status tabs without a page flash, so that browsing my Library is fluid (SCE-25).
19. As a returning user, I want recommendations to refresh on a sensible cadence without me pressing a button, so that the app feels alive but uncluttered (respects ADR "Remove manual Tasks").

## Implementation Decisions

### Modules to build or modify

- **Recommendation engine (new deep module).** Two stages — embedding-based candidate retrieval + Gemini rerank/explain. Replaces the heuristic `build_taste_profile` node in `app/agents/graph.py`. Full design in ADR-0002.
- **`RankingService` (deepen, do NOT delete — supersedes SCE-18's "delete" option).** Becomes the orchestration seam for the retrieve→rerank pipeline and ranking invalidation.
- **`Recommendation` model (revive + repurpose — supersedes SCE-6's deletion).** Backs the continuous Discovery agent's proactive finds (it already carries `agent_type`, `reasoning`, `source_urls`, `dismissed`, `saved_to_library`). `SearchLog` may still be deleted under SCE-6.
- **Discovery agent (new).** A LangGraph agent run by a **Scheduled Job**, persisting through injected repositories (follows SCE-17). Never user-triggered (respects ADR "Remove manual Tasks").
- **Onboarding flow (new).** Swipe UI + "why" chips → writes a seed Taste Profile via `LibraryService` without requiring Library Items.
- **Signal model.** Ratings + Watch Status weighting + "why" tags + cast/crew features. Per-status weighting decisions live in ADR-0002.
- **`Content` schema additions.** Cast/crew (ADR-0003); `platform` / `release_type` and structured release dates (ADR-0004).
- **Auto-Reminder logic.** Discovery/enrichment populates release data; a Scheduled Job creates `release`/`premiere` Reminders automatically.
- **Library UX (SCE-25, must-fix).** JSON APIs for add/remove/status + in-place DOM updates + no-reload tab switching.

### Glossary impact (requires CONTEXT.md update)

`CONTEXT.md` currently lists **Recommendation** as a deprecated synonym for **Ranking**. This PRD revives **Recommendation** as a *distinct* concept: an agent-discovered candidate (often not yet ranked, possibly with external sources), as opposed to **Ranking** = a score for catalog Content against a Taste Profile. The glossary must be updated to define both. See ADR-0002.

### Architecture decisions (recorded as ADRs)

- **ADR-0002** — Recommendation engine: commit to the two-stage retrieve→rerank architecture; **start embeddings-first (Gemini)**, add **LightFM as a second retrieval source later** once interaction volume justifies it. Batch retraining via Scheduled Jobs.
- **ADR-0003** — Cast/crew data model + which Providers supply it (OMDb `Actors`, TVMaze cast, TVDB people).
- **ADR-0004** — Release-date / OTT-platform sourcing and the auto-Reminder pipeline.
- **ADR-0005** — Frontend: add a Tailwind build step pre-launch; **SCE-25 is a committed launch fix**; islands-vs-SPA direction decided here, build deferred post-launch.

### Boundaries

- **Always:** run new background work as **Scheduled Jobs** on Celery Beat (ADR-001 Production Readiness, ADR "Remove manual Tasks"); inject repositories into agents (SCE-17); route Library/ranking mutations through `LibraryService` / deepened `RankingService`; use glossary vocabulary.
- **Ask first:** any new external dependency (e.g. a vector index library, LightFM), schema migrations on `Content`, adding a paid data source.
- **Never:** reintroduce user-triggered Tasks / SSE progress (removed in SCE-31); call an LLM in the hot retrieval path over the full Catalog; block the first session on having a Library.

## Testing Decisions

- **What makes a good test:** assert external behavior (a seeded profile yields non-empty, plausibly-ranked candidates; a dropped title lowers similar scores; an add mutation returns updated state without a reload contract), not internal embedding values.
- **Modules to test:** the recommendation engine's candidate-retrieval and signal-weighting (deterministic given fixed embeddings/fixtures); `RankingService` invalidation; auto-Reminder creation from release data; the SCE-25 JSON API endpoints.
- **Prior art:** `tests/test_periodic_tasks.py` (Scheduled Job behavior), `tests/test_remove_manual_tasks.py` (regression guard for the no-manual-tasks decision), `tests/conftest.py` fixtures.
- Gemini rerank and live Provider calls are mocked; mark anything hitting real services `@pytest.mark.integration`.

## Out of Scope

- **Pre-launch:** LightFM / collaborative filtering (deferred to post-launch second retrieval source — ADR-0002); a full SPA rewrite (ADR-0005 defers the build); mood-based filtering; a daily email/push digest; full social features.
- **Permanently (for now):** competing with Netflix-scale collaborative filtering; hosting full article text for Gossip; LLM generating items live in the retrieval loop.

## Further Notes — conflict resolutions on existing issues

- **SCE-6** (remove dead models): narrow to deleting `SearchLog` only; **keep `Recommendation`** (repurposed here).
- **SCE-21** (taste-profile bias): do not patch `build_taste_profile`; its open questions become the signal-weighting design in ADR-0002. Mark blocked-by this PRD.
- **SCE-25** (no-reload Library): **committed launch must-fix.** JSON APIs and no-reload behavior stand regardless of the ADR-0005 frontend direction.
- **SCE-18** (pass-through services): choose "deepen," not "delete," for `RankingService`.
- **SCE-5** (rename `Content.source`→`provider`): land before the ADR-0003/0004 `Content` migrations to avoid migration collisions.
- **SCE-17** (inject repos into agents): enabler for the Discovery agent; keep.
