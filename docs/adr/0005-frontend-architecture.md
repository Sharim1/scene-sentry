# ADR-0005: Frontend Architecture — Tailwind Build Now, Islands Later, SCE-25 Committed

**Status:** Accepted
**Date:** 2026-06-20
**Deciders:** @sharimpervez
**Related:** PRD [Personalized Discovery & Recommendations](../prd/personalized-discovery-and-recommendations.md); SCE-25 (no-reload Library); SCE-8 (CSP/security headers).

---

## Context

The frontend is server-rendered Jinja2 + Tailwind (loaded via **CDN** in dev) + Alpine.js, with a ~3,300-line vanilla `static/js/app.js`, no `package.json`, and no build step. Two pressures converge:

1. **Production readiness.** The Tailwind CDN ships the entire framework unpurged, is slow, and is hostile to the CSP added in SCE-8.
2. **New rich interactions.** The taste onboarding (swipe + "why" chips) and the recommendation feed need more interactivity than the current hand-rolled approach comfortably supports, which raises the "do we need a separate frontend app?" question.

Meanwhile **SCE-25** (eliminate full-page reloads on Library mutations and tab switching) is mostly implemented with Alpine + JSON APIs and has been flagged as an important launch fix.

## Decision

**Add a Tailwind build step before launch. Treat SCE-25 as a committed launch fix. Decide the bigger frontend direction here as "islands," but defer the build until after launch — do not do a full SPA rewrite before launch.**

1. **Pre-launch (must):** introduce a minimal Node toolchain (`package.json` + a bundler) to compile and purge Tailwind (kill the CDN) and bundle/split `app.js`. One move, two wins (CSS size/CSP + JS maintainability).
2. **SCE-25 (committed launch fix):** ship no-reload add/remove/status mutations and no-flash tab switching. The **JSON API endpoints and the no-reload behavior are reusable regardless of any future frontend direction** and are required by the onboarding feature anyway. The behavior requirement is non-negotiable; only the *implementation tech* may migrate later.
3. **Direction (decided, build deferred):** when richer interactivity is built post-launch, prefer an **islands** approach — keep Jinja server rendering for most pages, add targeted rich components (built with the new toolchain) only where interactivity demands it (swipe onboarding, recommendation feed). **Reject a full SPA rewrite** for launch.

## Alternatives Considered

- **Full SPA rewrite (React/Next/SvelteKit) against FastAPI as a JSON API.** Cleaner long-term component model and a great Clerk React SDK story, but a large rewrite right before production that discards the working Jinja templates and most of `app.js`, and directly conflicts with SCE-25's in-flight work. **Rejected for launch** (may be reconsidered far later if interactivity needs outgrow islands).
- **Keep the CDN + hand-rolled Alpine indefinitely.** Lowest effort, but the CDN is a real production/CSP problem and the 3,300-line `app.js` is a maintainability smell. **Rejected.**
- **Islands now (build the toolchain + components pre-launch).** Tempting, but only the Tailwind build is truly launch-critical; building the islands toolchain out fully now risks slipping launch. **Deferred** to post-launch.

## Consequences

**Easier:** production-grade CSS (purged, CSP-friendly); a real bundler unlocks splitting `app.js` and building the onboarding/feed components cleanly later; SCE-25 delivers the smooth daily-use feel the retention goal needs.

**Harder / new:** introduces a Node toolchain to a previously Python-only repo (dev setup + CI step); the hand-rolled Alpine/PJAX tab plumbing in SCE-25 may eventually be superseded by island components (accepted — the JSON APIs carry over).

**To revisit:** whether islands suffice or a heavier framework is warranted once the onboarding/feed are built and measured; consolidating `app.js` into modules during the bundler migration.
