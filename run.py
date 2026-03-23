#!/usr/bin/env python3
"""
Scene Sentry Application Entry Point

Run with: python run.py
Or: uvicorn app.main:app --reload --host 0.0.0.0 --port 5000
"""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )

