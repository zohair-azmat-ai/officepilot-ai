"""
config.py — Central configuration loaded from .env

Template cell mapping is based on the REAL company quotation format:
  - 14-column layout (A–N), 47 rows
  - Company header/logo block: A1:M11 (merged, do not touch)
  - Client / header section: rows 12–16
  - Item table: rows 18–35 (header row 18, item slots rows 19–35)
  - Totals: rows 36–40
"""

import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_template_path() -> str:
    """
    Resolve the template path that works in all three execution contexts:

    1. Development  : path relative to this file (project root / templates/)
    2. Packaged exe : OFFICEPILOT_RESOURCE_DIR env var set by Electron main.js
                      to <resourcesPath>/backend/
    3. PyInstaller  : sys._MEIPASS contains extracted bundle resources
    """
    # Electron packaged mode — main.js sets this to resourcesPath/backend/
    resource_dir = os.environ.get('OFFICEPILOT_RESOURCE_DIR')
    if resource_dir:
        return str(Path(resource_dir) / 'templates' / 'quotation_template.xlsx')

    # PyInstaller frozen bundle
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'templates' / 'quotation_template.xlsx')

    # Development: resolve relative to this file
    return str(Path(__file__).parent.parent / 'templates' / 'quotation_template.xlsx')


class Settings(BaseSettings):
    # ── Paths ──────────────────────────────────────────────────────────────────
    # Root folder that contains year/month sub-folders for quotations
    # Example:  G:\NEW DATA 2021\DRIVE\Quotation
    QUOTATION_BASE_PATH: str = r"G:\NEW DATA 2021\DRIVE\Quotation"

    # Path to the Excel template file.
    # Auto-resolved for dev / packaged / PyInstaller contexts (see above).
    # Override by setting TEMPLATE_PATH in .env.
    TEMPLATE_PATH: str = _default_template_path()

    # ── Server ─────────────────────────────────────────────────────────────────
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000

    # ── Excel cell mapping (real company template) ─────────────────────────────
    #
    # Rules:
    #  • Always specify the TOP-LEFT cell of a merged range.
    #  • openpyxl silently ignores writes to non-top-left cells in a merge.
    #
    # Verified cell positions from template inspection:
    #
    #   Header block
    #   ─────────────────────────────────────────────────────────────────────
    #   B12   Client name       (merged B12:G12)
    #   K14   Ref number        (merged K14:L14)  — formatted as YYYY/MM/XXXX
    #   K16   Date              (merged K16:L16)  — formatted as DD/M/YYYY
    #
    #   Item table  (row 20 = first item slot)
    #   ─────────────────────────────────────────────────────────────────────
    #   A20   Serial number     (standalone)      — always written as 1
    #   B20   Description       (merged B20:G20)
    #   B21   Size/spec         (merged B21:G21)  — second description line
    #   H20   Quantity          (merged H20:I20)
    #   J20   Unit price        (merged J20:K20)
    #   L20   Line amount       (standalone)      — computed: qty × rate
    #
    #   Totals
    #   ─────────────────────────────────────────────────────────────────────
    #   L36   Subtotal          (standalone)      — same as L20 for single item
    #   L37   VAT / tax         (standalone)
    #   L38   Total amount      (standalone)      — A38:K38 is the label; L38 is value
    #   L40   Total amount copy (top of L40:L41)  — repeated for the bottom section
    #
    CELL_MAP: dict[str, str] = {
        # Header
        "client_name": "B12",
        "ref_no":      "K14",   # formatted by excel_writer as YYYY/MM/XXXX
        "date":        "K16",   # formatted by excel_writer as DD/M/YYYY
        # Item row 1
        "s_no":        "A20",
        "description": "B20",
        "size":        "B21",
        "quantity":    "H20",
        "rate":        "J20",
        "amount":      "L20",   # computed: quantity × rate
        # Totals
        "subtotal":    "L36",   # quantity × rate  (pre-VAT total)
        "tax":         "L37",   # VAT amount
        "total":       "L38",   # final total (rate×qty + tax)
        "total_copy":  "L40",   # same total repeated in the bottom section
    }

    # ── Cells to clear before writing ─────────────────────────────────────────
    # These cells contain old data from the template file (previous quotation
    # values). They are reset to None each time a new quotation is generated so
    # no leftover data bleeds into the new file.
    #
    # Each entry must be the TOP-LEFT cell of its merged range (or a standalone
    # cell). Never list a non-top-left cell in a merged range here.
    #
    CELLS_TO_CLEAR: list[str] = [
        # Header — optional/no-form fields from previous quotation
        "B13",   # Attn name            (merged B13:G13)
        "B14",   # TRN / TRNT number    (merged B14:G14)
        # Item 1 overflow rows (description can span row 22 in multi-line entries)
        "B22",   # Description line 3   (merged B22:G22)
        # Item 2 slot — wipe all data so only item 1 appears
        "A24",   # Serial no 2          (standalone)
        "B24",   # Description item 2   (merged B24:G24)
        "H24",   # Qty item 2           (merged H24:I24)
        "J24",   # Unit price item 2    (merged J24:K24)
        "L24",   # Amount item 2        (standalone)
        "B25",   # Desc overflow item 2 (merged B25:G25)
        "B26",   # Desc overflow item 2 (merged B26:G26)
        # Amount-in-words section (not auto-generated in MVP)
        "C40",   # Amount in words line 1 (merged C40:K40)
        "C41",   # Amount in words line 2 (merged C41:K41)
    ]

    # ── LibreOffice ────────────────────────────────────────────────────────────
    # Common install paths on Windows — first match found will be used.
    LIBREOFFICE_PATHS: list[str] = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        r"C:\Program Files\LibreOffice 7\program\soffice.exe",
        r"C:\Program Files\LibreOffice 24\program\soffice.exe",
    ]

    # ── Telegram Bot ───────────────────────────────────────────────────────────
    # Get your token from @BotFather on Telegram.
    TELEGRAM_BOT_TOKEN: str = ""

    # Comma-separated list of Telegram chat IDs allowed to use this bot.
    # Example: "123456789" or "123456789,987654321"
    # Get your chat ID by messaging @userinfobot on Telegram.
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""

    # Set to true to enable the Telegram bot on backend startup.
    TELEGRAM_ENABLED: bool = False

    @property
    def telegram_allowed_ids(self) -> list[int]:
        """Parse TELEGRAM_ALLOWED_CHAT_IDS into a list of ints."""
        if not self.TELEGRAM_ALLOWED_CHAT_IDS:
            return []
        return [
            int(x.strip())
            for x in self.TELEGRAM_ALLOWED_CHAT_IDS.split(",")
            if x.strip().lstrip("-").isdigit()
        ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Singleton — import `settings` everywhere instead of re-instantiating
settings = Settings()
