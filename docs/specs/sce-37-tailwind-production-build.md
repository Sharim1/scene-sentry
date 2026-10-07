# Spec: SCE-37 — Tailwind production build (remove CDN) + bundle `app.js`

**Status:** Implemented (Tailwind v3; visual redesign explicitly out of scope)
**Date:** 2026-06-21
**Issue:** [SCE-37](https://linear.app/scene-sentry/issue/SCE-37) (parent: SCE-32 PRD; related: SCE-8 security headers)
**ADR:** [0005 Frontend Architecture](../adr/0005-frontend-architecture.md)

---

## Objective

Replace the dev-time **Tailwind CDN** with a real, purged, minified production CSS build, and bundle the
hand-rolled `static/js/app.js` — by introducing a minimal Node toolchain. This is a **production-readiness +
CSP fix**, not a feature: rendered pages must be **visually and behaviourally identical** to before.

**Why:**
- The Tailwind CDN ships the entire framework unpurged (large, slow) and JIT-compiles in the browser via `eval`.
- It forces the CSP (SCE-8) to allow `https://cdn.tailwindcss.com` in `script-src`, `style-src`, and `connect-src`.
- ADR-0005 commits to adding a Tailwind build step before launch and bundling `app.js`, while explicitly
  **rejecting a full SPA rewrite** for launch.

**Success looks like:** the CDN host is gone from every template and from the CSP; a purged stylesheet and a
bundled script are served from `/static/dist/`; every page looks the same; dev/CI/deploy know how to build them.

## Assumptions

1. **Tailwind v3**, reusing the existing `tailwind.config.js` (CommonJS, full theme) as the single source of
   truth. (v4's CSS-first config is a larger, riskier change for a no-visual-change task.)
2. **Toolchain = Tailwind CLI + esbuild**, orchestrated by npm scripts. No Vite / SPA dev server.
3. **`static/css/app.css` stays served as-is** — it is plain CSS (no `@apply`/`@tailwind`/`@layer`), so it needs
   no build. The build only produces the Tailwind utility/base/components layer that the CDN used to generate.
4. **Build artifacts live in `static/dist/` and are gitignored**, built in dev/CI/deploy (confirmed).
5. **Scope = Tailwind CDN + `app.js` only.** Alpine.js, Lucide, Clerk, and Google Fonts CDNs are out of scope.
   `'unsafe-eval'` and `'unsafe-inline'` remain in the CSP (Alpine + inline scripts still need them).
6. **`app.js` already assigns its Alpine-facing functions to `window.*`** (`notificationBell`, `libraryCounts`,
   `showToast`, `initGlobalCatalogSearch`, `refreshClerkToken`), so bundling as an IIFE is safe. Module splitting
   is a stretch/follow-up.

> **Note:** ADR-0005 / SCE-37 describe `app.js` as "~3,300 lines"; it is **835 lines** today. No impact on approach.

## Tech Stack / Toolchain decisions

| Concern | Decision | Rationale |
|---|---|---|
| CSS compile + purge | **`tailwindcss` v3 CLI** | Reuses existing `tailwind.config.js`; no PostCSS config needed |
| JS bundle + minify | **`esbuild`** | Tiny, fast, zero-config; `--format=iife` preserves the `window.*` globals |
| Script orchestration | **npm scripts** + `npm-run-all` (`run-p`) for parallel watch | Avoids a heavier task runner |
| Dev server / HMR | **None** | Server-rendered Jinja; watchers rebuild assets, the FastAPI reloader serves them |

**New Node dependencies (devDependencies — require approval per PRD "Ask first: any new external dependency"):**
- `tailwindcss@^3`
- `esbuild` (latest)
- `npm-run-all` (latest) — for `run-p` parallel watchers
- `@tailwindcss/forms` / `@tailwindcss/typography` — **only if** the class audit (below) finds they were
  implicitly relied on. Default: **not added.**

## Commands

```bash
# One-time
npm install                 # installs the Node toolchain (writes package-lock.json)

# Production build (also what CI / deploy run)
npm run build               # = build:css && build:js

# Individual builds
npm run build:css           # tailwindcss -i static/css/tailwind.entry.css -o static/dist/tailwind.css --minify
npm run build:js            # esbuild static/js/app.js --bundle --minify --format=iife --outfile=static/dist/app.js

# Dev (watch both, rebuild on change)
npm run dev                 # run-p dev:css dev:js
```

Python dev workflow is unchanged (`python run.py`), with one new prerequisite: run `npm run build` (or
`npm run dev` in a second terminal) once so `static/dist/` exists.

## Project Structure

New / changed files:

```
package.json                      → NEW: scripts + devDependencies
package-lock.json                 → NEW: committed lockfile
static/css/tailwind.entry.css     → NEW: @tailwind base/components/utilities (build input only)
static/dist/                      → NEW (gitignored): built output
  ├── tailwind.css                →   purged + minified Tailwind, replaces the CDN
  └── app.js                      →   bundled + minified app.js
static/css/app.css                → UNCHANGED, still served as-is (custom component CSS)
static/js/app.js                  → REWORKED into a thin entry that imports static/js/src/*
static/js/src/*.js                → NEW: the split modules (build input via the entry)
tailwind.config.js                → UNCHANGED (already correct; content globs verified)
templates/base.html               → swap CDN include → <link dist/tailwind.css>; script → dist/app.js
templates/base_public.html        → swap CDN include → <link dist/tailwind.css>
templates/index.html              → swap CDN include → <link dist/tailwind.css>
templates/partials/_tailwind_cdn.html → DELETED
app/main.py                       → drop cdn.tailwindcss.com from CSP (script/style/connect-src)
.gitignore                        → add node_modules/ and static/dist/
.github/workflows/ci.yml          → NEW frontend-build job (Node + npm ci + npm run build + assert outputs)
docs/CONTRIBUTING.md, README.md   → document the build step
tests/test_no_tailwind_cdn.py     → NEW regression guard
```

## Approach

### 1. CSS pipeline
- Create `static/css/tailwind.entry.css` containing only:
  ```css
  @tailwind base;
  @tailwind components;
  @tailwind utilities;
  ```
- `tailwindcss` CLI compiles it against `tailwind.config.js` → `static/dist/tailwind.css`, **purged** to the
  classes found in `tailwind.config.js`'s `content` globs (`./templates/**/*.html`, `./static/js/**/*.js`) and
  **minified**.
- `tailwind.config.js` is a **superset** of the trimmed inline config in `_tailwind_cdn.html` (it adds
  `popover`/`input`/`ring`/`accent-foreground`, the full `sidebar` palette, `borderRadius`, keyframes/animations),
  so the compiled output is at worst a superset of what the CDN produced — never a regression.
- Templates load the compiled file **before** `static/css/app.css` (preserving today's cascade order: CDN-styles
  first, custom CSS second), so custom component classes (`.btn`, `.sidebar-nav-item`, `.toast*`) still win.

### 2. JS pipeline (split into modules — confirmed)
- **Refactor** the single `static/js/app.js` into focused ES modules under `static/js/src/`, with
  `static/js/app.js` becoming the thin entry that imports them and re-exposes the Alpine-facing functions on
  `window.*`. Proposed module split (one concern each):
  - `src/csrf.js` — `getCsrfToken`, the `window.fetch` CSRF wrapper
  - `src/clerk.js` — `refreshClerkToken` (+ `window.refreshClerkToken`)
  - `src/icons.js` — Lucide init guard
  - `src/notifications.js` — `notificationBell` (+ `window.notificationBell`)
  - `src/toasts.js` — `initToasts`, `showToast` (+ `window.showToast`)
  - `src/library.js` — `libraryCounts` (+ `window.libraryCounts`), `popstate` handler, library events
  - `src/tabs.js`, `src/forms.js`, `src/genre.js`, `src/cards.js`, `src/confirm.js`
  - `src/util.js` — `timeAgo`, `debounce`
  - `src/search.js` — `initGlobalCatalogSearch` (+ `window.initGlobalCatalogSearch`)
- `esbuild static/js/app.js --bundle --minify --format=iife --outfile=static/dist/app.js`.
- IIFE format + the preserved `window.X = X` assignments keep Alpine inline expressions
  (`x-data="notificationBell()"`, etc.) resolving exactly as today.
- **Behaviour-preservation is the hard constraint.** Functions that currently call each other via globals
  (e.g. `notificationBell` → `window.showToast`) must keep working — either via explicit `import` or by
  continuing to reach through `window.*`. No behaviour change; this is a pure source reorganisation.

### 3. Template wiring
- In `base.html`, `base_public.html`, `index.html`: replace `{% include 'partials/_tailwind_cdn.html' %}` with
  `<link rel="stylesheet" href="{{ static_url('dist/tailwind.css') }}">`.
- In `base.html`: change the bottom `<script src="{{ static_url('js/app.js') }}">` to `dist/app.js`.
- Delete `templates/partials/_tailwind_cdn.html`.
- (Optional, low-risk) extend `static_url` to append `?v={app_version}` for cache-busting. **Default: skip**
  unless we want it now.

### 4. CSP (SCE-8)
In `app/main.py`'s `SecurityHeadersMiddleware`, remove `https://cdn.tailwindcss.com` from `script-src`,
`style-src`, and `connect-src`. Leave everything else (Alpine/jsdelivr, Lucide/unpkg, Clerk, fonts,
`'unsafe-eval'`, `'unsafe-inline'`) untouched.

### 5. CI / deploy
- Add a `frontend-build` job to `ci.yml`: `actions/setup-node`, `npm ci`, `npm run build`, then assert both
  `static/dist/tailwind.css` and `static/dist/app.js` exist and are non-empty.
- Deploy must run `npm run build` before/at release so `static/dist/` is present in the served image
  (exact deploy wiring depends on Open Question 1).

### 6. Class-purge audit (correctness risk)
Tailwind only keeps classes it can find as literal strings in the `content` globs. Before finishing:
- Grep `static/js/app.js` for dynamically **constructed** class strings (concatenation / template literals).
  Conditional literals like `n.is_read ? 'bg-transparent' : 'bg-primary'` are fine (literal substrings); only
  string-built class names are at risk.
- If any are found, add them to a `safelist` in `tailwind.config.js`.

## Code Style

- npm scripts stay declarative and readable; no shell glue beyond `run-p`.
- `package.json`: `"private": true`, `"type": "commonjs"` (matches the CommonJS `tailwind.config.js`).
- Pin major versions in `package.json`; commit `package-lock.json`.
- Commits follow Conventional Commits (e.g. `build: add Tailwind production build and bundle app.js`).

## Testing Strategy

- **Regression guard (`tests/test_no_tailwind_cdn.py`)** — mirrors the repo's existing guard pattern
  (`tests/test_remove_manual_tasks.py`):
  - assert no file under `templates/` contains `cdn.tailwindcss.com`;
  - assert `templates/partials/_tailwind_cdn.html` no longer exists;
  - assert the CSP string built by `SecurityHeadersMiddleware` does **not** contain `cdn.tailwindcss.com`;
  - assert `base.html` references `dist/tailwind.css` and `dist/app.js`.
- **CI build assertion** — `npm run build` succeeds and produces non-empty `static/dist/tailwind.css` and
  `static/dist/app.js`.
- **Manual visual parity** — load and eyeball each surface (dev server, in dark mode): `/` (landing),
  `/login`, `/register`, `/dashboard`, `/movies`, `/tv-shows`, `/gossip`, `/library` (incl. status tabs +
  add/remove), `/reminders`, `/settings`, a content detail page, the notification bell dropdown, the global
  search modal, and a flash/toast message. (Optional: capture before/after screenshots with the browser tools.)
- `pytest`, `ruff`, `mypy` remain green; template rendering in tests is unaffected (`static_url` returns a
  string regardless of whether the file exists).

## Boundaries

- **Always:** keep pages visually/behaviourally identical; reuse `tailwind.config.js` as the theme source of
  truth; keep `static/css/app.css` as-is; use Conventional Commits; commit the lockfile.
- **Ask first:** adding any Node dependency beyond `tailwindcss` + `esbuild` + `npm-run-all`; committing built
  assets to git; touching Alpine/Lucide/Clerk CDN usage or `'unsafe-eval'`/`'unsafe-inline'`.
- **Never:** rewrite to an SPA (ADR-0005); change the visual design; remove CSP protections beyond the single
  `cdn.tailwindcss.com` host; edit generated files in `static/dist/` by hand.

## Success Criteria

1. No template (and no Python file) references `https://cdn.tailwindcss.com`; `_tailwind_cdn.html` is deleted.
2. The CSP no longer lists `cdn.tailwindcss.com` in any directive; the app loads with no CSP violations in the
   browser console.
3. `npm run build` produces a **purged, minified** `static/dist/tailwind.css` (substantially smaller than the
   full framework) and a **bundled, minified** `static/dist/app.js` (from the split `static/js/src/*` modules),
   both served in place of the CDN / raw source.
4. All listed pages render identically to `main` and all interactive behaviours still work (notification bell,
   global search, library add/remove/tabs, toasts) — i.e. the `app.js` module split is behaviour-preserving.
5. `npm run dev` rebuilds CSS and JS on change.
6. CI runs the frontend build and asserts the outputs; `pytest`/`ruff`/`mypy` stay green.
7. Dev setup and the build step are documented in `README.md` and `docs/CONTRIBUTING.md`.

## Resolved decisions

1. **Built assets:** gitignore `static/dist/`; build in CI/deploy. Deploy target must run `npm run build`
   (Node available at deploy/build time).
2. **Cache-busting:** out of scope for SCE-37 (handle hashing in a later task).
3. **`app.js` module split:** **yes, in scope** — split into modules now (see JS pipeline §2).

4. **Tailwind version:** **v3**, reusing `tailwind.config.js` (confirmed).
5. **Visual polish:** **out of scope** for SCE-37 (AC is "visually identical"); to be handled later, enabled by
   this build step.

## Plan

Implementation order (each step verifiable before the next):

1. **Toolchain bootstrap** — `package.json` (+ scripts, devDeps: `tailwindcss@^3`, `esbuild`, `npm-run-all`),
   `static/css/tailwind.entry.css`, `.gitignore` entries. Verify: `npm install` then `npm run build:css`
   produces a non-empty purged `static/dist/tailwind.css`.
2. **JS module split** — break `static/js/app.js` into `static/js/src/*` modules + thin entry; `npm run build:js`
   produces `static/dist/app.js`. Verify: bundle builds; spot-check that `window.*` globals are still assigned.
3. **Template + CSP wiring** — swap CDN → `dist/tailwind.css` and `js/app.js` → `dist/app.js` in the three base
   templates; delete `_tailwind_cdn.html`; drop `cdn.tailwindcss.com` from the CSP. Verify: app boots, pages
   render, no CSP console violations.
4. **Class-purge audit** — scan `app.js`/templates for dynamically-built class strings; safelist if needed.
   Verify: manual visual parity across all listed surfaces.
5. **Tests + CI + docs** — `tests/test_no_tailwind_cdn.py`; `frontend-build` CI job; update `README.md` and
   `docs/CONTRIBUTING.md`. Verify: `pytest`/`ruff`/`mypy` green; CI build asserts outputs.

**Risks:** (a) purge dropping dynamically-constructed classes → mitigated by the audit + safelist; (b) the JS
split changing behaviour → mitigated by keeping `window.*` assignments and manual interaction testing;
(c) deploy needing Node → tracked, deploy wiring updated to run `npm run build`.

## Tasks

- [x] **T1 — Node toolchain bootstrap.**
  - Acceptance: `package.json` with `build`/`build:css`/`build:js`/`dev`/`dev:css`/`dev:js` scripts and pinned
    devDeps; `static/css/tailwind.entry.css`; `node_modules/` + `static/dist/` gitignored; `package-lock.json`
    committed.
  - Verify: `npm install && npm run build:css` → non-empty `static/dist/tailwind.css`.
  - Files: `package.json`, `package-lock.json`, `static/css/tailwind.entry.css`, `.gitignore`.
- [x] **T2 — Split `app.js` into modules.**
  - Acceptance: `static/js/src/*` modules + thin `static/js/app.js` entry; all prior `window.*` functions still
    exposed; no behaviour change.
  - Verify: `npm run build:js` → `static/dist/app.js`; grep confirms `window.notificationBell`/`libraryCounts`/
    `showToast`/`initGlobalCatalogSearch`/`refreshClerkToken` present in source entry.
  - Files: `static/js/app.js`, `static/js/src/*.js`.
- [x] **T3 — Template + CSP wiring.** (also reconciled `login`/`register` inline `destructive` to the canonical theme)
  - Acceptance: base templates load `dist/tailwind.css` (before `app.css`) and `dist/app.js`;
    `_tailwind_cdn.html` deleted; CSP has no `cdn.tailwindcss.com`.
  - Verify: app boots; pages render; browser console shows no CSP violations.
  - Files: `templates/base.html`, `templates/base_public.html`, `templates/index.html`,
    `templates/partials/_tailwind_cdn.html` (delete), `app/main.py`.
- [x] **T4 — Purge audit + visual parity.** (no safelist needed; JS-sourced classes confirmed in compiled CSS)
  - Acceptance: no missing styles on any listed surface; safelist added only if needed.
  - Verify: manual walkthrough (+ optional before/after screenshots).
  - Files: `tailwind.config.js` (only if safelist needed).
- [x] **T5 — Tests, CI, docs.**
  - Acceptance: regression guard test passes; CI `frontend-build` job builds + asserts outputs; README +
    CONTRIBUTING document the build.
  - Verify: `pytest`/`ruff`/`mypy` green locally; CI green.
  - Files: `tests/test_no_tailwind_cdn.py`, `.github/workflows/ci.yml`, `README.md`, `docs/CONTRIBUTING.md`.
