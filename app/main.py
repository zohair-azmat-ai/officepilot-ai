"""
main.py — FastAPI application entry point.

Responsibilities
----------------
* Create the FastAPI app instance with lifespan context
* Configure logging
* Mount the static files directory (serves the HTML frontend at /)
* Include all API routers
* Start / stop the Telegram bot alongside the backend

To run:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
Or via the convenience script:
    python run.py
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.quotation  import router as quotation_router
from app.api.companies  import router as companies_router
from app.api.ledger     import router as ledger_router

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import settings

    logger.info("─" * 60)
    logger.info("OfficePilot AI — Quotation Agent started")
    logger.info("Base quotation path : %s", settings.QUOTATION_BASE_PATH)
    logger.info("Template path       : %s", settings.TEMPLATE_PATH)
    logger.info("Frontend            : http://%s:%d/", settings.APP_HOST, settings.APP_PORT)
    logger.info("API docs            : http://%s:%d/docs", settings.APP_HOST, settings.APP_PORT)

    # ── Start Telegram bot (optional) ─────────────────────────────────────
    if settings.TELEGRAM_ENABLED and settings.TELEGRAM_BOT_TOKEN:
        from app.services.telegram_bot import start_bot
        try:
            await start_bot(settings.TELEGRAM_BOT_TOKEN)
            logger.info("Telegram bot        : enabled and polling")
        except Exception as exc:
            logger.error("Telegram bot failed to start: %s", exc)
    else:
        logger.info("Telegram bot        : disabled (set TELEGRAM_ENABLED=true in .env)")

    logger.info("─" * 60)

    yield  # ← application runs here

    # ── Shutdown ───────────────────────────────────────────────────────────
    from app.services.telegram_bot import stop_bot
    await stop_bot()
    logger.info("OfficePilot AI — shutdown complete")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OfficePilot AI — Quotation Agent",
    description=(
        "Local Windows automation tool for generating quotation Excel files "
        "and PDFs from a template with sequential reference numbering."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(quotation_router)
app.include_router(companies_router)
app.include_router(ledger_router)

# ── Static files (HTML frontend) ───────────────────────────────────────────────
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def serve_frontend() -> FileResponse:
        """Serve the single-page HTML frontend."""
        return FileResponse(str(_static_dir / "index.html"))
