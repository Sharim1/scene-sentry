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
    app_name: str = "MovieMind"
    app_version: str = "2.0.0"
    debug: bool = True
    env: str = "development"  # development, staging, production
    secret_key: str = "dev-secret-key-change-in-production"
    session_secret: Optional[str] = None
    
    # Database
    database_url: str = "sqlite:///./moviemind.db"
    
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
    tmdb_api_key: Optional[str] = None
    brightdata_api_key: Optional[str] = None
    
    # Background Tasks
    discovery_interval_minutes: int = 30
    gossip_scrape_interval_minutes: int = 30
    
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
        """Check if Clerk authentication is properly configured"""
        return bool(self.clerk_issuer and self.clerk_publishable_key)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()