# syntax=docker/dockerfile:1

# Scene Sentry application image.
#
# Primary use: run the Celery worker + beat on the $4/mo DigitalOcean droplet
# (Postgres/Redis are provided via env). The web process on FastAPI Cloud is
# built by the platform from pyproject.toml/uv.lock and does NOT use this image,
# but the image can also serve the web locally (default CMD) so docker-compose
# can bring up the full stack.

# ---- Stage 1: build frontend assets (static/dist/*) ----
FROM node:20-slim AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
# tailwind scans templates + static/js; esbuild bundles static/js/app.js
COPY tailwind.config.js ./
COPY static ./static
COPY templates ./templates
RUN npm run build

# ---- Stage 2: python runtime ----
# uv-provided image pins a matching uv + Python 3.11.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS runtime

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install third-party dependencies first for a cache-friendly layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the source, add the built assets, then install the project itself.
COPY . .
COPY --from=assets /build/static/dist ./static/dist
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run as non-root; give Celery beat a writable location for its schedule file.
RUN mkdir -p /data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Local convenience default; docker-compose overrides this with the Celery
# worker / beat commands on the droplet.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
