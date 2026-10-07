# ADR-0003: Cast & Crew Data Model and Provider Sourcing

**Status:** Accepted
**Date:** 2026-06-20
**Deciders:** @sharimpervez
**Related:** PRD [Personalized Discovery & Recommendations](../prd/personalized-discovery-and-recommendations.md); ADR-0002 (cast/crew are inputs to Content embeddings); sequence after SCE-5.

---

## Context

Cast and crew are a primary reason many people choose what to watch, and ADR-0002 wants them as **Content** embedding features and as the basis for the onboarding "why = Cast" signal. Today `Content` stores only `director` (movie) and `author` (book) as plain strings — there is **no cast list and no structured crew**. We need real people data, attributable across **Providers**, deduplicated like Content.

## Decision

**Introduce first-class people data linked to Content via a credits join, populated during Discovery/Enrichment from the providers that supply it.**

- **`Person`** — a deduplicated individual (name, external IDs per provider, optional metadata). Dedup mirrors Content: shared external ID first, normalized-name fallback.
- **`Credit`** — the link between a `Person` and a **Content**, carrying `role` (`cast` | `director` | `writer` | `creator` | …), `character` (for cast), and `billing_order` (for ranking top-billed cast).
- `Content.director` is retained for backward compatibility during migration, then sourced from `Credit` (`role=director`).

### Provider sourcing

| Provider | Cast | Crew | Notes |
|---|---|---|---|
| OMDb | `Actors` (top few, comma string) | `Director`, `Writer` | Shallow but free; parse the strings |
| TVMaze | Cast endpoint (person + character) | Crew endpoint | Richest free TV source |
| TVDB | People / characters | People | Movies + TV |
| TMDb | Full credits | Full credits | **Disabled** (commercial license) — schema must not depend on it |

Cast/crew are filled by the existing **Enrichment** path (gaps backfilled from whichever provider has the data; first provider to supply a field wins, others fill blanks), consistent with current dedup/merge behavior. Top-billed cast only (e.g. first ~10) to bound storage and embedding noise.

## Alternatives Considered

- **JSON blob of cast/crew on `Content`.** Simple, but not queryable ("show me everything with this actor"), no dedup of people across titles, weak as embedding input. **Rejected.**
- **Keep only `director`/`author` strings and skip cast.** Cheapest, but defeats ADR-0002's cast-aware matching and the "why = Cast" signal. **Rejected.**
- **Depend on TMDb's full credits.** Best data, but TMDb is disabled for licensing. **Rejected** — schema stays provider-agnostic.

## Consequences

**Easier:** cast/crew become embedding features and a first-class signal; enables "more from this actor/director" and people-based discovery; people are deduplicated and reusable.

**Harder / new:** a new ingestion concern (people dedup) and two new tables + migrations on a hot model — **must land after SCE-5's `Content.source`→`provider` rename** to avoid colliding migrations; provider cast coverage is uneven (free tiers are shallow), so embeddings must tolerate missing/partial credits.

**To revisit:** how many cast members to store/embed; whether to surface a public people/credits UI (out of scope for launch).
