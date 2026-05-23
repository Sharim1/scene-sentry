# Contributing

Practical guide for making changes to Scene Sentry.

---

## Getting started

```bash
# Install dependencies
uv sync

# Copy and fill in env vars
cp .env.example .env

# Run the dev server (auto-reloads on file change)
python run.py

# Run tests
pytest

# Lint + type check
ruff check .
mypy app/
```

The app starts at `http://localhost:8000`. You do not need all API keys — disable unused providers in `.env` (`TVMAZE_ENABLED=false`, etc.).

---

## Project conventions

### Language / terminology

Use the domain vocabulary from [CONTEXT.md](../CONTEXT.md). The most common mistakes:

- **Content** not "media" or "title" (when referring to a catalog entry)
- **Library Item** not "watchlist item" or "bookmark"
- **Watch Status** not "tracking status"
- **Gossip** not "news" or "article"
- **Ranking** not "recommendation" (the `Recommendation` model is legacy and unused)
- **Provider** not "source" (source = origin publication of a Gossip item)
- **Discovery** = first-time catalog ingestion; **Enrichment** = filling gaps on existing rows

### Code style

- Linting: `ruff` (configured in `pyproject.toml`). Run `ruff check . --fix` before committing.
- Type checking: `mypy app/`. All new code should be fully typed.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `refactor:`, `docs:`, etc.
- No inline comments unless the why is non-obvious. Don't comment what the code does — name it well instead.

---

## Where to put new code

| What you're adding | Where |
|---|---|
| New database table | `app/models/` + migration or `init_db()` |
| Database query | `app/repositories/` — one repo per model |
| Business logic | `app/services/` |
| HTTP endpoint | `app/routes/` |
| New content source (external API) | `app/services/providers/` — implement `ContentProvider` |
| AI/LLM pipeline | `app/agents/` |
| Background job | `app/tasks/scheduler.py` |
| New config/env var | `app/config.py` (Pydantic Settings) |
| Reusable template fragment | `templates/partials/` |

### Layer rules

- Routes call services. Routes do **not** call repositories or external APIs directly.
- Services call repositories and providers. Services own transaction boundaries (`db.commit()`).
- Repositories do SQL only. No business logic, no cross-repo calls.
- Agents are called from services. Agents do not touch the database directly — services write the results.

---

## Adding a new page / route

1. Add the route function to the appropriate file in `app/routes/` (or create a new one for a new section).
2. If adding a new router file, include it in `app/main.py` with `app.include_router(...)`.
3. Add a template in `templates/`. Extend `base.html`.
4. Use `OptionalUserDep` for public pages, `RequireAuthDep` for authenticated-only pages.
5. No direct DB access in the route — instantiate the relevant service or repository.

---

## Adding a new model

1. Create `app/models/your_model.py`. Import `Base` from `app/database.py`.
2. Add the import to `app/models/__init__.py` so `init_db()` picks it up.
3. Create `app/repositories/your_model_repo.py`.
4. If this model has relationships to existing models, add the `relationship()` on both sides.
5. Run `pytest` — the in-memory SQLite test DB is rebuilt from `Base.metadata.create_all()` on each run, so your new table will appear automatically.

---

## Adding a background task

1. Write the business logic in a service (not in the scheduler).
2. Add the APScheduler job to `app/tasks/scheduler.py`.
3. Make the scheduler function call the service — keep the scheduler thin.
4. If the task should also be triggerable on-demand from the UI, wire it through `TaskManager` (see `task_manager.py` and `routes/api.py`).

---

## Testing

Test files live in `tests/`. Use the fixtures from `conftest.py`:

```python
def test_something(db_session):
    repo = ContentRepository(db_session)
    # ... each test gets a fresh transaction that rolls back after
```

- Don't mock the database. Tests run against real SQLAlchemy with in-memory SQLite.
- Mark slow or integration tests with `@pytest.mark.slow` or `@pytest.mark.integration`.
- LLM calls and external HTTP should be mocked in unit tests.

---

## PR checklist

- [ ] `ruff check .` passes
- [ ] `mypy app/` passes
- [ ] `pytest` passes
- [ ] Used domain vocabulary from CONTEXT.md
- [ ] No business logic in routes; no SQL in routes
- [ ] New config values documented in ARCHITECTURE.md (Configuration table)
- [ ] New models documented in MODELS.md
- [ ] Commit messages follow Conventional Commits

---

## Useful commands

```bash
# Manually trigger content discovery
python manage.py discover

# Manually trigger enrichment
python manage.py enrich

# Backfill user emails from Clerk
python manage.py fix-emails

# Run with coverage
pytest --cov=app --cov-report=html
open htmlcov/index.html
```
