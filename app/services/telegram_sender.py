"""
services/telegram_sender.py — Low-level Telegram send helpers.

Wraps bot.send_message and bot.send_document with error isolation so a
failed send never crashes the handler.
"""
import logging
from pathlib import Path

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


async def send_text(bot: Bot, chat_id: int, text: str) -> bool:
    """Send an HTML-formatted text message. Returns True on success."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as exc:
        logger.error("send_text to %s failed: %s", chat_id, exc)
        return False


async def send_document(
    bot: Bot,
    chat_id: int,
    file_path: str | Path,
    caption: str = "",
) -> bool:
    """Send a local file as a Telegram document. Returns True on success."""
    path = Path(file_path)
    if not path.exists():
        logger.error("File not found, cannot send: %s", path)
        return False
    try:
        with open(path, "rb") as fh:
            await bot.send_document(
                chat_id=chat_id,
                document=fh,
                filename=path.name,
                caption=caption,
            )
        return True
    except Exception as exc:
        logger.error("send_document to %s failed: %s", chat_id, exc)
        return False
