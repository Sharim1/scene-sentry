"""
Application configuration using Pydantic Settings
"""

import os
from functools import lru_cache

from pydantic import ConfigDict, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # App
    app_name: str = "Scene Sentry"
    app_version: str = "2.0.0"
    debug: bool = False
    env: str = "development"  # development, staging, production
    secret_key: str = "dev-secret-key-change-in-production"
    session_secret: str | None = None

    # Database
    database_url: str = "postgresql://scenesentry:scenesentry@localhost:5432/scenesentry"

    # Clerk Auth
    clerk_secret_key: str | None = None
    clerk_publishable_key: str | None = None
    clerk_webhook_secret: str | None = None
    clerk_issuer: str | None = None
    # Comma-separated list of authorized parties (origins) for azp claim verification
    clerk_authorized_parties: str | None = None

    # AI APIs
    gemini_api_key: str | None = None
    tavily_api_key: str | None = None

    # Content provider API keys
    tmdb_api_key: str | None = None
    tvdb_api_key: str | None = None
    omdb_api_key: str | None = None
    tvmaze_api_key: str | None = None  # Optional; public API works without it

    # Content provider feature flags (provider is active only when enabled AND key is present)
    tmdb_enabled: bool = False  # Requires commercial license for revenue projects
    tvdb_enabled: bool = True
    omdb_enabled: bool = True
    tvmaze_enabled: bool = True

    # Email delivery (Mailgun primary, Resend fallback)
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = None
    mailgun_from_email: str | None = None  # defaults to noreply@<mailgun_domain>
    resend_api_key: str | None = None
    resend_from_email: str | None = None  # e.g. "Scene Sentry <noreply@alerts.scenesentry.com>"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Background Tasks
    gossip_scrape_interval_minutes: int = 30
    reranking_interval_minutes: int = 120
    discovery_interval_hours: int = 6
    discovery_batch_size: int = 10  # pages per provider per scheduled run
    enrichment_interval_minutes: int = 15  # how often to backfill episode/detail data
    reminder_check_interval_minutes: int = 1  # how often to check for due reminders

    # Embeddings (SCE-33)
    embedding_enabled: bool = True
    embedding_model: str = "models/text-embedding-004"
    embedding_dim: int = 768
    embedding_interval_minutes: int = 30
    embedding_batch_size: int = 100

    # Public contact form (override CONTACT_TO_EMAIL in .env)
    contact_to_email: str | None = "contact@example.com"
    contact_from_email: str | None = None  # defaults via effective_contact_from_address

    # Rate limiting
    rate_limit_auth: str = "5/minute"  # For login/register endpoints
    rate_limit_api: str = "60/minute"  # For API endpoints

    # Trusted hosts for TrustedHostMiddleware (comma-separated). "*" disables the
    # Host check (default); set to the production domain(s) once known (SCE-41).
    allowed_hosts: str = "*"

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Ensure secret key is changed in production"""
        env = os.getenv("ENV", "development")
        if v == "dev-secret-key-change-in-production" and env == "production":
            raise ValueError("SECRET_KEY must be changed in production environment")
        return v

    @field_validator("clerk_webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, v: str | None) -> str | None:
        """Validate webhook secret format if provided"""
        if v and not v.startswith("whsec_"):
            raise ValueError("CLERK_WEBHOOK_SECRET should start with 'whsec_'")
        return v

    @model_validator(mode="after")
    def _validate_production_config(self) -> "Settings":
        """Fail fast on insecure dev defaults when ENV=production.

        Keeps development/test (the default env) untouched while ensuring a
        production deploy never boots against the local dev database, SQLite, or
        a shared/undefined session secret.
        """
        if self.env != "production":
            return self
        if self.database_url == "postgresql://scenesentry:scenesentry@localhost:5432/scenesentry":
            raise ValueError("DATABASE_URL must point at the production database when ENV=production")
        if self.database_url.startswith("sqlite"):
            raise ValueError("SQLite is not supported in production; use Postgres with pgvector")
        if not self.session_secret or self.session_secret == self.secret_key:
            raise ValueError("SESSION_SECRET must be set and distinct from SECRET_KEY when ENV=production")
        return self

    @property
    def clerk_authorized_parties_list(self) -> list[str]:
        """Parse authorized parties from comma-separated string"""
        if not self.clerk_authorized_parties:
            return []
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]

    @property
    def clerk_frontend_api_host(self) -> str | None:
        """Host of the Clerk Frontend API, derived from CLERK_ISSUER.

        For a Clerk development instance this is a `*.clerk.accounts.dev` host;
        for a production instance it is the custom FAPI domain (e.g.
        `clerk.scenesentry.com`). Used to allow-list Clerk in the CSP so the
        Clerk JS/XHR/frames load under the production custom domain.
        """
        if not self.clerk_issuer:
            return None
        return self.clerk_issuer.replace("https://", "").replace("http://", "").rstrip("/") or None

    @property
    def allowed_hosts_list(self) -> list[str]:
        """Parsed TrustedHost allow-list; empty list means no restriction ('*')."""
        if not self.allowed_hosts or self.allowed_hosts.strip() == "*":
            return []
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def is_clerk_configured(self) -> bool:
        """Check if Clerk authentication is properly configured (requires secret for SDK verification)."""
        return bool(self.clerk_secret_key and self.clerk_publishable_key)

    @property
    def effective_contact_from_address(self) -> str:
        """From-address for outbound contact-form emails."""
        if self.contact_from_email:
            return self.contact_from_email
        if self.resend_from_email:
            return self.resend_from_email
        if self.mailgun_domain:
            return self.mailgun_from_email or f"Scene Sentry <noreply@{self.mailgun_domain}>"
        return "Scene Sentry <noreply@localhost>"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
