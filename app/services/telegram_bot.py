"""
services/telegram_bot.py — Telegram bot lifecycle manager.

Integrates python-telegram-bot v20+ with FastAPI's asyncio event loop.
The bot runs as a background polling task on the same loop as uvicorn —
no threads, no subprocesses.

Usage (from FastAPI lifespan):
    await start_bot(token)   # on startup
    await stop_bot()         # on shutdown
"""
import logging

from telegram.ext import Application, MessageHandler, filters

from app.services.telegram_handlers import handle_message

logger = logging.getLogger(__name__)


class TelegramBot:
    """Wraps the python-telegram-bot Application for clean start/stop."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._app: Application | None = None

    async def start(self) -> None:
        if self._app is not None:
            logger.warning("Telegram bot already running — ignoring duplicate start()")
            return

        self._app = Application.builder().token(self._token).build()

        # Register handlers — add more here for future command groups
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        self._app.add_handler(
            MessageHandler(filters.COMMAND, handle_message)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message"],
        )
        logger.info("Telegram bot polling started")

    async def stop(self) -> None:
        if self._app is None:
            return
        try:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped cleanly")
        except Exception as exc:
            logger.error("Error stopping Telegram bot: %s", exc)
        finally:
            self._app = None


# ── Module-level singleton ────────────────────────────────────────────────────

_bot_instance: TelegramBot | None = None


async def start_bot(token: str) -> None:
    """Create and start the singleton bot. Safe to call once at startup."""
    global _bot_instance
    if _bot_instance is not None:
        logger.warning("start_bot() called while bot already running — ignored")
        return
    _bot_instance = TelegramBot(token)
    await _bot_instance.start()


async def stop_bot() -> None:
    """Stop and destroy the singleton bot. Safe to call at shutdown."""
    global _bot_instance
    if _bot_instance is not None:
        await _bot_instance.stop()
        _bot_instance = None
