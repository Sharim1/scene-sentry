"""
Application configuration using Pydantic Settings
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # App
    app_name: str = "MovieMind"
    app_version: str = "2.0.0"
    debug: bool = True
    secret_key: str = "dev-secret-key-change-in-production"
    session_secret: Optional[str] = None  # ADD THIS
    
    # Database
    database_url: str = "sqlite:///./moviemind.db"
    
    # Clerk Auth
    clerk_secret_key: Optional[str] = None
    clerk_publishable_key: Optional[str] = None
    clerk_webhook_secret: Optional[str] = None
    clerk_issuer: Optional[str] = None  # ADD THIS
    
    # AI APIs
    gemini_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    tmdb_api_key: Optional[str] = None
    brightdata_api_key: Optional[str] = None
    
    # Background Tasks
    discovery_interval_minutes: int = 30
    gossip_scrape_interval_minutes: int = 30
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # ADD THIS to ignore extra env vars
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()