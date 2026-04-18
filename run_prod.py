"""
run_prod.py — Production launcher for the packaged Electron app.

Differences from run.py:
  • reload=False  — no file-watcher (reduces CPU; not needed in production)
  • Respects OFFICEPILOT_RESOURCE_DIR so uvicorn finds the right working paths
    when run from inside process.resourcesPath (Electron packaged mode).
"""

import os
import sys

# PyInstaller frozen bundle: tell config.py where resources are extracted to.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    os.environ.setdefault('OFFICEPILOT_RESOURCE_DIR', sys._MEIPASS)

import uvicorn
from app.config import settings

if __name__ == '__main__':
    uvicorn.run(
        'app.main:app',
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=False,
        log_level='info',
    )
