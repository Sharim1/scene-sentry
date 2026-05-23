# Scene Sentry — Architecture

## What it is

Scene Sentry is a server-side-rendered web app for tracking and discovering movies and TV shows. It pulls content from external APIs (TMDb, TVDB, TVMaze, OMDb), stores it in a local database, ranks it against each user's taste using Gemini, and scrapes entertainment news via Tavily. Auth is handled by Clerk.

---

## Tech stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async, ASGI) |
| Server | Uvicorn |
| Templates | Jinja2 (server-side HTML) |
| Styling | Tailwind CSS |
| Database ORM | SQLAlchemy 2.0 (sync sessions) |
| Database | PostgreSQL (production), SQLite (dev/test) |
| Auth | Clerk (JWT middleware + webhooks) |
| AI / LLM | LangChain + LangGraph + Gemini |
| Web search | Tavily |
| Background jobs | APScheduler (async) |
| Email | Resend (primary) + Mailgun (fallback) |
| Rate limiting | slowapi |
| Config | Pydantic Settings (`.env`) |

---

## High-level architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Client Browser                       │
│      (Jinja2 Templates + Tailwind CSS + Alpine.js)      │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/HTTPS
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI Application                      │
│  Middleware: ClerkAuth → Session                         │
│  Routes → Services → Repositories → Database            │
└───┬──────────────┬──────────────┬───────────────────────┘
    │              │              │
┌───▼───┐   ┌─────▼─────┐   ┌───▼──────────┐
│  DB   │   │ LangGraph │   │   Redis      │
│SQLite/│   │ Re-ranking│   │ (broker +    │
│Postgres│  │  Agent    │   │  task state) │
└───────┘   └─────┬─────┘   └──┬───────┬──┘
                  │             │       │
    ┌─────────────┼─────────────┘       │
    │             │                     │
┌───▼───┐  ┌─────▼─────┐  ┌───▼──────┐ │
│ TMDB  │  │  Tavily   │  │  Gemini  │ │
│ TVDB  │  │ (gossip)  │  │  (LLM)   │ │
└───────┘  └───────────┘  └──────────┘ │
                                       │
              ┌────────────────────────┘
              │
    ┌─────────▼──────────┐
    │   Celery Worker    │
    │   + Celery Beat    │
    │  (periodic tasks)  │
    └────────────────────┘
```

---

## Directory map

```
scene-sentry/
├── run.py                      # Uvicorn entry point
├── manage.py                   # CLI for admin tasks (discover, enrich, fix-emails)
├── pyproject.toml
│
├── app/
│   ├── main.py                 # FastAPI app, middleware, router includes, lifespan
│   ├── config.py               # Pydantic Settings — all env vars & feature flags
│   ├── database.py             # Engine, SessionLocal, get_db(), db_session context manager
│   ├── dependencies.py         # FastAPI Depends: DbDep, OptionalUserDep, RequireAuthDep
│   ├── templates.py            # Jinja2 env setup, custom filters
│   │
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── user.py             # User (local + Clerk)
│   │   ├── content.py          # Content (movies, TV shows)
│   │   ├── episode.py          # Episode (TV show episodes)
│   │   ├── library.py          # LibraryItem (user tracking)
│   │   ├── gossip.py           # Gossip (scraped news headlines)
│   │   ├── notification.py     # Notification (in-app alerts)
│   │   ├── reminder.py         # Reminder (scheduled alerts)
│   │   ├── ranking.py          # UserContentRank (personalized scores)
│   │   ├── recommendation.py   # Recommendation (legacy, unused — see SCE-6)
│   │   └── discovery_state.py  # DiscoveryState (pagination cursor per provider)
│   │
│   ├── repositories/           # One repo per model, pure SQL — no business logic
│   │   ├── content_repo.py
│   │   ├── episode_repo.py
│   │   ├── library_repo.py
│   │   ├── gossip_repo.py
│   │   ├── notification_repo.py
│   │   ├── reminder_repo.py
│   │   └── ranking_repo.py
│   │
│   ├── routes/                 # Thin HTTP handlers — parse input, call service, render
│   │   ├── auth.py             # /login, /register, /logout
│   │   ├── dashboard.py        # /dashboard
│   │   ├── content.py          # /movies, /tv-shows, /{content_id}
│   │   ├── library.py          # /library/*
│   │   ├── gossip.py           # /gossip
│   │   ├── notifications.py    # /notifications/*
│   │   ├── reminders.py        # /reminders/*
│   │   ├── api.py              # /api/* (JSON, SSE task progress)
│   │   └── contact.py          # /contact
│   │
│   ├── services/
│   │   ├── content_discovery.py    # Orchestrates provider fetching + dedup + upsert
│   │   ├── library_service.py      # Add, update, rate — with ranking invalidation
│   │   ├── gossip_service.py       # Triggers GossipScraperAgent
│   │   ├── notification_service.py # Build and send notifications
│   │   ├── ranking_service.py      # Runs ContentRankingGraph per user
│   │   ├── reminder_service.py     # Schedule and dispatch reminders
│   │   ├── email_service.py        # Abstract email dispatch (Resend/Mailgun)
│   │   ├── resend_service.py
│   │   ├── mailgun_service.py
│   │   ├── contact_service.py
│   │   ├── identity_sync.py        # Clerk → local User sync
│   │   ├── task_manager.py         # On-demand task tracking + SSE progress
│   │   ├── tvdb_service.py         # TVDB episode enrichment
│   │   │
│   │   └── providers/              # External content API abstraction
│   │       ├── base.py             # ContentProvider ABC + NormalizedContent DTO
│   │       ├── registry.py         # get_active_providers() factory
│   │       ├── tvmaze_provider.py
│   │       ├── tvdb_provider.py
│   │       ├── omdb_provider.py
│   │       └── tmdb_provider.py
│   │
│   ├── agents/
│   │   ├── graph.py            # ContentRankingGraph (LangGraph, 5-node pipeline)
│   │   └── gossip_agent.py     # GossipScraperAgent (Tavily search → Gossip rows)
│   │
│   ├── middleware/
│   │   └── clerk.py            # ClerkAuthMiddleware (JWT validation, user sync)
│   │
│   ├── tasks/
│   │   └── scheduler.py        # APScheduler job definitions
│   │
│   ├── celery_app.py                   # Celery instance + Beat schedule
│   │
│   └── tasks/
│       └── periodic.py             # Celery periodic tasks
│
├── templates/                  # Jinja2 HTML
│   ├── base.html
│   ├── index.html
│   ├── dashboard.html
│   ├── movies.html
│   ├── tv_shows.html
│   ├── content_detail.html
│   ├── library.html
│   ├── gossip/feed.html
│   ├── reminders.html
│   ├── settings.html
│   ├── partials/               # Reusable template fragments
│   └── errors/
│
├── static/                     # CSS, JS, images
├── tests/
│   ├── conftest.py             # in-memory SQLite fixtures
│   ├── test_config.py
│   └── test_health.py
└── docs/                       # You are here
```

---

## Layered architecture

Every request follows this path. Layers only call inward — routes never touch the database directly, repositories never call services.

```
Route → Service → Repository → DB
           │
           ├── Provider  (outbound HTTP to content APIs)
           └── Agent     (LangGraph / LLM pipelines)
```

**Routes** — parse HTTP inputs, call one service method, render a template or return JSON. No SQL, no external HTTP.

**Services** — all business logic. Own transaction boundaries (`db.commit()`). Orchestrate repos, providers, and agents. Side effects (ranking invalidation, notification creation) happen here.

**Repositories** — thin wrappers around SQLAlchemy queries. One file per model. No business logic; no cross-repo calls.

**Providers** — implement `ContentProvider` ABC. Fetch and normalize content from a single external API. See [PROVIDERS.md](PROVIDERS.md).

**Agents** — LangGraph stateful pipelines for AI-driven work (ranking, gossip scraping). Called from services, never from routes.

---

## Middleware chain

Middleware executes outer-first (last registered = outermost):

```
Incoming request →
  SecurityHeadersMiddleware (CSP, HSTS, X-Frame-Options)
    CSRFMiddleware (token validation)
      SessionMiddleware (cookie sessions via itsdangerous)
        ClerkAuthMiddleware (JWT → user_id, user sync)
          FastAPI route handler
```

`ClerkAuthMiddleware` (`app/middleware/clerk.py`) decodes the Clerk JWT, looks up or creates the local `User` row, and injects `request.state.user` and `request.state.clerk_user_id`. Routes read from `request.state` via the `OptionalUserDep` / `RequireAuthDep` dependencies.

---

## Dependency injection

Three core FastAPI dependencies used across all routes:

```python
DbDep          = Annotated[Session, Depends(get_db)]         # SQLAlchemy session
OptionalUserDep = Annotated[User | None, Depends(...)]       # current user, may be None
RequireAuthDep  = Annotated[User, Depends(...)]              # 401 if not authenticated
```

---

## Background tasks

APScheduler runs in the same process as the web server. Jobs call the same services that routes use.

Periodic jobs run via **Celery Beat + Celery Worker**, backed by **Redis** as both broker and result backend. This replaces the previous in-process APScheduler — jobs now execute in a separate worker process, avoiding duplicate execution when running multiple web workers.

On-demand tasks (manual gossip scrape, manual re-ranking) use a **Redis-backed TaskManager** for state persistence and Redis Pub/Sub for real-time SSE progress updates across workers.

| Task | Interval | What it does |
|---|---|---|
| Content Discovery | 6 hours | Pulls movies/TV from providers; seeds on first run, syncs after |
| Content Enrichment | 15 min | Backfills episodes, runtime, and details on sparse records |
| Gossip Scraping | 30 min | Searches Tavily for entertainment news, stores headline + preview |
| Content Re-ranking | 2 hours | Runs `ContentRankingGraph` for each user |
| Reminders | 1 min | Processes due reminders, creates notifications, sends emails |
| Cleanup | 24 hours | Removes old gossip, sent reminders, and read notifications |

---

## AI ranking pipeline

`ContentRankingGraph` in `agents/graph.py` is a 5-node LangGraph pipeline:

```
build_taste_profile → select_candidates → batch_score → write_rankings → validate_quality
                                                                               │
                                              ← (loop back if low diversity) ──┘
```

| Node | LLM? | What it does |
|---|---|---|
| `build_taste_profile` | No | Aggregates genre frequencies, avg ratings, type ratios from the user's Library |
| `select_candidates` | No | SQL query for unranked or stale Content matching top genres |
| `batch_score` | Yes (Gemini) | Sends taste profile + up to 20 candidates per batch; returns 0–100 scores + reasoning |
| `write_rankings` | No | Upserts scores into `UserContentRank` |
| `validate_quality` | No | Checks result diversity; loops back to `select_candidates` if insufficient |

Rankings are invalidated (stale-flagged) whenever a user changes a Library Item's status or rating.

---

## Configuration

All config lives in `app/config.py` as a Pydantic `Settings` class loaded from `.env`.

| Variable | Required | Purpose |
|---|---|---|
| `REDIS_URL` | Yes | Redis connection for Celery broker + task state (default: `redis://localhost:6379/0`) |
| `TMDB_API_KEY` | Yes | Movie/TV data from TMDb |
| `TAVILY_API_KEY` | Yes | Gossip headline scraping |
| `GEMINI_API_KEY` | Recommended | AI re-ranking via Gemini LLM |
| `TVDB_API_KEY` | Optional | Episode-level TV data |
| `OMDB_API_KEY` | Optional | IMDb ratings and metadata |
| `CLERK_SECRET_KEY` | Optional | Clerk server-side JWT validation |
| `CLERK_PUBLISHABLE_KEY` | Optional | Clerk frontend SDK |
| `RESEND_API_KEY` | Optional | Email delivery (primary) |
| `MAILGUN_API_KEY` | Optional | Email delivery (fallback) |

Feature flags (`TVMAZE_ENABLED`, `TMDB_ENABLED`, etc.) gate providers at startup. A provider with no API key and no feature flag is excluded from `get_active_providers()`.

---

## Security

- **CSP / HSTS / X-Frame-Options** — set by `SecurityHeadersMiddleware` on every response.
- **CSRF** — `starlette-csrf` validates tokens on all state-changing requests.
- **Sessions** — encrypted cookies via `itsdangerous`.
- **Auth** — Clerk JWT; local session fallback for non-Clerk setups.
- **Rate limiting** — `slowapi` on auth and public API endpoints.
- **XSS** — Jinja2 auto-escaping enabled globally.
- **External links** — gossip source links rendered with `rel="noopener noreferrer"`.
- **Secrets** — never hardcoded; all from `config.py` / environment.

---

## Entry points

**`python run.py`** — starts Uvicorn on `0.0.0.0:8000`. FastAPI lifespan hook calls `init_db()` (create tables) and `start_scheduler()`.

**`python manage.py <command>`** — admin CLI:
- `discover` / `discover --full` / `discover --provider tvmaze --pages 20`
- `enrich` / `enrich --all`
- `fix-emails` — backfill real emails from Clerk

---

## Testing

Tests live in `tests/`. The `conftest.py` creates an in-memory SQLite engine (session-scoped) and a per-test transaction that rolls back after each test. Async tests use `asyncio_mode = "auto"`.

```bash
pytest                   # run all tests
pytest -m "not slow"     # skip integration-tagged tests
pytest --cov=app         # with coverage
```

Coverage excludes `app/tasks/` and `app/agents/` (background/LLM work not suitable for unit tests).

---

## Related docs

- [PROVIDERS.md](PROVIDERS.md) — how content providers work, how to add a new one
- [DATA_FLOWS.md](DATA_FLOWS.md) — step-by-step traces for key user actions
- [MODELS.md](MODELS.md) — database schema reference
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to add features, style guide, PR checklist
- [../CONTEXT.md](../CONTEXT.md) — domain language glossary (canonical terminology)
