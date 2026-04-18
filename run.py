"""
run.py — Convenience launcher.

Usage:
    python run.py

This reads APP_HOST / APP_PORT from .env so you only change the config in
one place.
"""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,            # auto-restart on file changes during development
        log_level="info",
    )
