"""
MovieMind - AI-powered entertainment discovery and gossip platform
"""
from app.main import app
from app.database import db_session, engine, Base

__all__ = ["app", "db_session", "engine", "Base"]

