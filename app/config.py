"""
Application configuration using Pydantic Settings
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # App
    app_name: str = "Scene Sentry"
    app_version: str = "2.0.0"
    debug: bool = True
    env: str = "development"  # development, staging, production
    secret_key: str = "dev-secret-key-change-in-production"
    session_secret: Optional[str] = None
    
    # Database
    database_url: str = "postgresql://scenesentry:scenesentry@localhost:5432/scenesentry"
    
    # Clerk Auth
    clerk_secret_key: Optional[str] = None
    clerk_publishable_key: Optional[str] = None
    clerk_webhook_secret: Optional[str] = None
    clerk_issuer: Optional[str] = None
    # Comma-separated list of authorized parties (origins) for azp claim verification
    clerk_authorized_parties: Optional[str] = None
    
    # AI APIs
    gemini_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None

    # Content provider API keys
    tmdb_api_key: Optional[str] = None
    tvdb_api_key: Optional[str] = None
    omdb_api_key: Optional[str] = None
    tvmaze_api_key: Optional[str] = None   # Optional; public API works without it

    # Content provider feature flags (provider is active only when enabled AND key is present)
    tmdb_enabled: bool = False   # Requires commercial license for revenue projects
    tvdb_enabled: bool = True
    omdb_enabled: bool = True
    tvmaze_enabled: bool = True

    # Email delivery (Mailgun primary, Resend fallback)
    mailgun_api_key: Optional[str] = None
    mailgun_domain: Optional[str] = None
    mailgun_from_email: Optional[str] = None  # defaults to noreply@<mailgun_domain>
    resend_api_key: Optional[str] = None
    resend_from_email: Optional[str] = None   # e.g. "Scene Sentry <noreply@alerts.scenesentry.com>"
    
    # Background Tasks
    gossip_scrape_interval_minutes: int = 30
    reranking_interval_minutes: int = 120
    discovery_interval_hours: int = 6
    discovery_batch_size: int = 10   # pages per provider per scheduled run
    enrichment_interval_minutes: int = 15  # how often to backfill episode/detail data
    reminder_check_interval_minutes: int = 1  # how often to check for due reminders
    
    # Public contact form (override CONTACT_TO_EMAIL in .env)
    contact_to_email: Optional[str] = "contact@example.com"
    contact_from_email: Optional[str] = None  # defaults via effective_contact_from_address

    # Rate limiting
    rate_limit_auth: str = "5/minute"  # For login/register endpoints
    rate_limit_api: str = "60/minute"  # For API endpoints
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @field_validator('secret_key')
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Ensure secret key is changed in production"""
        env = os.getenv("ENV", "development")
        if v == "dev-secret-key-change-in-production" and env == "production":
            raise ValueError("SECRET_KEY must be changed in production environment")
        return v
    
    @field_validator('clerk_webhook_secret')
    @classmethod
    def validate_webhook_secret(cls, v: Optional[str]) -> Optional[str]:
        """Validate webhook secret format if provided"""
        if v and not v.startswith("whsec_"):
            raise ValueError("CLERK_WEBHOOK_SECRET should start with 'whsec_'")
        return v
    
    @property
    def clerk_authorized_parties_list(self) -> List[str]:
        """Parse authorized parties from comma-separated string"""
        if not self.clerk_authorized_parties:
            return []
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]
    
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


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()