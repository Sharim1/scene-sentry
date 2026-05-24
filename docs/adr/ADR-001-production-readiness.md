# ADR-001: Production Readiness — Component Upgrades

**Status:** In Progress
**Date:** 2026-05-23
**Deciders:** @sharimpervez

---

## Context

Scene Sentry is a working MVP (v2.1.7) that runs as a single-process FastAPI monolith. The question is whether the current component choices are production-viable, or whether swaps (e.g. RabbitMQ + Celery, Redis, Alembic) are prerequisites before deploying to real users.

After auditing every layer of the codebase, here is what I found.

---

## Current State Assessment

### What IS production-ready (keep as-is)

| Component | Verdict | Why |
|---|---|---|
| **FastAPI + Uvicorn** | Good | Async, well-tested, great for this app's scale. No reason to move. |
| **SQLAlchemy 2.0 + PostgreSQL** | Good | Connection pooling configured (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=300`). Solid for the expected load. |
| **Clerk auth** | Good | Managed auth with JWT validation, handshake flow, and session fallback. Not a liability. |
| **Provider pattern** | Good | Clean abstraction. Providers are swappable. Dedup is thorough. |
| **Layered architecture** | Good | Route → Service → Repo layering is clean. No spaghetti. |
| **Security middleware** | Good | CSP, HSTS, CSRF, rate limiting, XSS protection all in place. |
| **LangGraph ranking pipeline** | Good | Well-structured 5-node graph with heuristic fallback when LLM is unavailable. |

### What NEEDS work (real production blockers)

| Component | Problem | Severity |
|---|---|---|
| **APScheduler (in-process)** | Scheduler lives in the web process. If you run >1 web worker, every worker runs its own copy of every job. No distributed locking. Jobs are lost on crash/restart with no retry. | **Critical** |
| **TaskManager (in-memory dict)** | All on-demand task state is stored in a Python dict. Lost on restart. No persistence. Doesn't work with multiple workers. The code even has a comment admitting this: *"In a production environment, you might want to use Redis."* | **Critical** |
| **No database migrations** | Using `create_all()` + hand-rolled `_run_migrations()` with raw `ALTER TABLE` statements. Works for one developer; breaks in production when schema changes need to be versioned and rolled back. | **High** |
| **No structured logging** | Using `basicConfig` with print-style formatting. No JSON logs, no request IDs, no correlation. Unusable for debugging in production. | **Medium** |
| **No health check depth** | `/health` returns `"healthy"` without checking DB connectivity, scheduler state, or external API reachability. Useless for load balancer probes. | **Medium** |
| **Session-based sessions (cookie)** | `SessionMiddleware` uses signed cookies via `itsdangerous`. Fine for small payloads, but if you ever need to invalidate sessions server-side (logout-everywhere, security incident), you can't — there's no server-side session store. | **Low** |

---

## Decisions

### Decision 1: Replace APScheduler with Celery + Redis (NOT RabbitMQ)

**The core problem:** APScheduler runs inside the web process. This means:
- If you scale to 2+ Uvicorn workers, every worker runs every scheduled job independently (gossip gets scraped N times, ranking runs N times, etc.)
- If the process crashes mid-job, the job is silently lost with no retry
- There's no visibility into running/failed jobs
- The scheduler starts jobs at boot time that immediately hit external APIs

**Why Celery + Redis, not RabbitMQ:**

| Dimension | Celery + Redis | Celery + RabbitMQ |
|---|---|---|
| Complexity | Low — Redis is one binary, you likely need it anyway (see Decision 2) | Higher — RabbitMQ is a separate service with its own config, plugins, and failure modes |
| Cost | Cheap — a small Redis instance handles both broker AND result backend | More — need a separate broker instance plus still need Redis for caching |
| Your workload | Periodic jobs (every 15 min–6 hours) + occasional on-demand tasks. This is not a high-throughput message queue. Redis handles this trivially. | RabbitMQ's strengths (routing, dead-letter queues, consumer groups) are overkill here |
| Celery Beat | Replaces APScheduler's interval triggers. Runs as a single beat process — no duplicate job problem | Same, but now you're managing two infra components instead of one |
| Team familiarity | Standard Python stack; Redis is universal | Adds Erlang/AMQP operational overhead |

**RabbitMQ would make sense if** you were building an event-driven microservices system with complex routing, fan-out, or exactly-once delivery requirements. Scene Sentry has ~6 periodic jobs and 2 on-demand task types. Redis as a broker is the right fit.

**What changes:**
1. Add `celery[redis]` to dependencies
2. Create `app/celery_app.py` with broker/backend config
3. Convert each scheduler function into a Celery task (same service calls, just decorated)
4. Create a `celery beat` schedule to replace APScheduler intervals
5. Run as separate processes: `celery -A app.celery_app worker` and `celery -A app.celery_app beat`
6. Remove `app/tasks/scheduler.py` and the `start_scheduler()` / `shutdown_scheduler()` lifecycle hooks

**Impact on existing code:** Minimal. The scheduler functions already call services — only the wrapper changes. Services are untouched.

---

### Decision 2: Add Redis for TaskManager + caching

**The core problem:** `TaskManager` is an in-memory singleton with a Python dict. It:
- Loses all task state on restart
- Doesn't work with >1 web worker (each worker has its own dict)
- Uses `asyncio.Queue` for SSE pub/sub, which is per-process

**What changes:**
1. Add `redis[hiredis]` to dependencies
2. Replace `TaskManager._tasks` dict with Redis hash/sorted set
3. Replace `asyncio.Queue`-based SSE with Redis Pub/Sub (publish task updates to a channel, each SSE connection subscribes)
4. Task state survives restarts and works across workers
5. Optionally use Redis for session storage too (replacing itsdangerous cookies with server-side sessions)

**Bonus — caching layer:**
Once Redis is in the stack, you get a free caching layer for:
- Provider API responses (reduce external API calls)
- Rendered template fragments (dashboard, gossip feed)
- Taste profiles (avoid recomputing on every ranking run)
- Rate limiting state (currently using in-memory slowapi storage)

---

### Decision 3: Add Alembic for database migrations

**The core problem:** Schema evolution is handled by:
1. `Base.metadata.create_all()` — only creates tables that don't exist, never alters
2. `_run_migrations()` — hand-rolled `ALTER TABLE` statements checked against `information_schema`

This is fragile:
- No rollback capability
- No version tracking (which migrations have run?)
- The hand-rolled approach uses raw SQL with string interpolation for column types
- Adding a new column requires editing `database.py` instead of generating a versioned migration file
- Not testable

**What changes:**
1. `alembic init alembic`
2. Configure `alembic/env.py` to use `app.database.Base.metadata` and `settings.database_url`
3. Generate initial migration from current schema: `alembic revision --autogenerate -m "initial"`
4. Delete `_run_migrations()` from `database.py`
5. Run `alembic upgrade head` in deployment scripts instead of `create_all()`

**Impact:** Zero impact on application code. Only the deployment/startup process changes.

---

### Decision 4: Structured logging (lower priority, do after 1-3)

**The core problem:** Current logging:
```python
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
```
No request IDs, no JSON output, no correlation between request and background task logs.

**What changes:**
1. Add `structlog` or `python-json-logger`
2. Add request ID middleware (generate UUID per request, attach to all log entries)
3. Configure JSON output for production, human-readable for development
4. Add Celery task ID to background job logs

---

### Decision 5: Deep health check (do with Decision 1-2)

**What changes:**
Expand `/health` to check:
- Database connectivity (`SELECT 1`)
- Redis connectivity (`PING`)
- Celery worker availability (inspect active workers)
- External API reachability (optional, behind `?deep=true`)

---

## What NOT to change

| Tempting upgrade | Why skip it |
|---|---|
| **Switch to async SQLAlchemy** | Current sync sessions work fine in `asyncio.to_thread()`. Async SA adds complexity without measurable benefit at this scale. |
| **Add a separate API gateway** | Single FastAPI process is fine. Nginx/Caddy as a reverse proxy is sufficient. |
| **Kubernetes** | Overkill. A PaaS (Render, Railway, Fly.io) with 2 web workers + 1 Celery worker + 1 beat + managed Redis + managed Postgres is the right deployment model. |
| **Event sourcing / CQRS** | The read/write patterns are simple. Repository pattern is sufficient. |
| **GraphQL** | Server-side rendered app with Jinja2. REST endpoints are appropriate. |
| **Replace Gemini with self-hosted LLM** | Cost and latency are fine for the ranking workload. Not worth the operational burden. |

---

## Implementation Order

```
Phase 1 — Infrastructure (do together, ~2-3 days)
├── 1. Add Redis
├── 2. Add Celery + Celery Beat (replaces APScheduler)
├── 3. Migrate TaskManager to Redis
└── 4. Add Alembic (replaces hand-rolled migrations)

Phase 2 — Observability (~1 day)
├── 5. Structured logging
└── 6. Deep health check

Phase 3 — Polish (optional, as needed)
├── 7. Server-side sessions (Redis-backed)
├── 8. Provider API response caching (Redis)
└── 9. Rate limiter backend (Redis, replacing in-memory)
```

Phase 1 is the production blocker. Phase 2 makes production operable. Phase 3 is nice-to-have.

---

## Consequences

**What becomes easier:**
- Scaling to multiple web workers (critical for real traffic)
- Deploying schema changes without fear
- Debugging production issues (structured logs, task persistence)
- Adding new background jobs (just decorate with `@celery.task`)

**What becomes harder:**
- Local dev setup now requires Redis (mitigate: docker-compose, or `redis-server` via Homebrew)
- Deployment has more processes (web, worker, beat) instead of one

**What we'll need to revisit:**
- Celery worker concurrency settings once we see real load
- Redis memory limits and eviction policies
- Whether to add Flower (Celery monitoring dashboard) for visibility

---

## Action Items

1. [x] Provision Redis (managed, e.g. Render Key Value, Upstash, or ElastiCache)
2. [x] Add `celery[redis]` and `redis[hiredis]` to `pyproject.toml`
3. [x] Create `app/celery_app.py` with task definitions
4. [x] Migrate APScheduler jobs to Celery Beat schedule
5. [x] Migrate `TaskManager` to Redis-backed storage
6. [ ] Add `alembic` and generate initial migration
7. [x] Remove `_run_migrations()` and `start_scheduler()` / `shutdown_scheduler()`
8. [x] Update deployment config (docker-compose.yml) for worker + beat processes
9. [ ] Add structured logging
10. [ ] Expand health check
