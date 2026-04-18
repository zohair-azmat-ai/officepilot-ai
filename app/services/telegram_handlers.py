"""
services/telegram_handlers.py — Telegram message routing and command handlers.

Routing logic
─────────────
  /start, /help, "help"  → show usage instructions
  any text               → try quotation parse-and-create flow

Future extensibility
─────────────────────
  Add elif blocks in handle_message() to route "invoice ...", "ledger ...",
  "payment ..." etc. to dedicated handler functions following the same pattern
  as _handle_quotation().
"""
import logging
from datetime import date as _date

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.services.command_parser import parse_quotation_command
from app.services.company_memory import lookup as company_lookup
from app.schemas.quotation import QuotationCreateRequest, QuotationItem
from app.services.quotation_service import create_quotation
from app.services.telegram_sender import send_text, send_document

logger = logging.getLogger(__name__)

# ── Static message strings ────────────────────────────────────────────────────

_UNAUTHORIZED = "⛔ Unauthorized. This bot only responds to its configured owner."

_HELP = (
    "👋 <b>OfficePilot AI — Quotation Bot</b>\n\n"
    "Send a multi-item quotation command:\n\n"
    "<pre>Create quotation for GULF EXTRUSION COMPANY LLC\n"
    "Item 1 FABRICATION OF SS ROLLER qty 1 rate 500\n"
    "Item 2 TEFLON ROUND BAR qty 2 rate 350</pre>\n\n"
    "Or a single-item command:\n\n"
    "<pre>Quote for ABB INDUSTRIES fabrication of hydraulic block qty 1 rate 950</pre>\n\n"
    "Company details (ATTN, TRN, phone) are filled automatically from memory.\n\n"
    "<i>More commands coming soon: invoices, ledger, payments.</i>"
)


# ── Security ──────────────────────────────────────────────────────────────────

def _is_allowed(chat_id: int) -> bool:
    allowed = settings.telegram_allowed_ids
    if not allowed:
        return False
    return chat_id in allowed


# ── Entry point ───────────────────────────────────────────────────────────────

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all incoming text messages."""
    if update.message is None or update.message.text is None:
        return

    chat_id = update.message.chat_id
    text    = update.message.text.strip()

    # ── Security gate ──────────────────────────────────────────────────────
    if not _is_allowed(chat_id):
        logger.warning("Rejected message from unauthorized chat_id=%s", chat_id)
        await send_text(context.bot, chat_id, _UNAUTHORIZED)
        return

    logger.info("Telegram message from chat_id=%s: %.80r", chat_id, text)

    lower = text.lower()

    # ── Route ──────────────────────────────────────────────────────────────
    if lower in ("/start", "/help", "help"):
        await send_text(context.bot, chat_id, _HELP)
        return

    # Future command groups (add elif blocks here):
    # elif lower.startswith("invoice "):
    #     await _handle_invoice(text, chat_id, context)
    #     return
    # elif lower.startswith("ledger") or lower.startswith("balance"):
    #     await _handle_ledger(text, chat_id, context)
    #     return

    # Default: treat everything as a quotation command
    await _handle_quotation(text, chat_id, context)


# ── Quotation handler ─────────────────────────────────────────────────────────

async def _handle_quotation(
    text: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    bot = context.bot

    # 1. Parse natural-language command ──────────────────────────────────────
    try:
        parsed_resp = parse_quotation_command(text)
    except Exception as exc:
        logger.exception("Parser crashed on text from chat_id=%s", chat_id)
        await send_text(bot, chat_id, f"❌ <b>Parse error:</b>\n<code>{exc}</code>")
        return

    if not parsed_resp.success or parsed_resp.parsed is None:
        await send_text(
            bot, chat_id,
            "❌ Could not parse your command.\n\n"
            "Try:\n<pre>Quote for CLIENT NAME Item 1 description qty 1 rate NNN</pre>",
        )
        return

    p = parsed_resp.parsed

    # 2. Enrich with company memory ──────────────────────────────────────────
    attn = trn = phone = fax = ""
    matches = company_lookup(p.client_name, max_results=1)
    if matches:
        best  = matches[0]
        attn  = best.attn
        trn   = best.trn
        phone = best.phone
        fax   = best.fax

    # 3. Build request ───────────────────────────────────────────────────────
    today = _date.today()

    items: list[QuotationItem] = [
        QuotationItem(
            description=it.description,
            size=it.size,
            quantity=it.quantity,
            rate=it.rate,
            amount=it.amount,
        )
        for it in p.items
    ]

    req = QuotationCreateRequest(
        year        = p.year  or str(today.year),
        month       = p.month or str(today.month).zfill(2),
        date        = p.date  or today.strftime("%d-%m-%Y"),
        client_name = p.client_name,
        items       = items,
        attn        = attn,
        trn         = trn,
        phone       = phone,
        fax         = fax,
        description = p.description,
        size        = p.size,
        quantity    = p.quantity,
        rate        = p.rate,
        tax         = p.tax,
        total       = p.total,
    )

    # 4. Create quotation ────────────────────────────────────────────────────
    try:
        result = create_quotation(req)
    except Exception as exc:
        logger.exception("Quotation creation failed for chat_id=%s", chat_id)
        await send_text(bot, chat_id, f"❌ <b>Quotation creation failed:</b>\n<code>{exc}</code>")
        return

    # 5. Format reply ────────────────────────────────────────────────────────
    ref_str   = f"{req.year}/{req.month}/{result.new_ref_number:04d}"
    total_fmt = f"AED {req.total:,.2f}"

    pdf_line = "📄 PDF: ready" if result.pdf_status == "created" else "📄 PDF: not available"
    reply = (
        "✅ <b>Quotation Created</b>\n\n"
        f"Client: <b>{p.client_name}</b>\n"
        f"Ref No: <code>{ref_str}</code>\n"
        f"Total: <b>{total_fmt}</b>\n"
        f"File: <code>{result.filename}</code>\n"
        f"{pdf_line}"
    )

    if parsed_resp.warnings:
        warn_lines = "\n".join(f"• {w}" for w in parsed_resp.warnings[:3])
        reply += f"\n\n⚠️ <i>Notes:</i>\n{warn_lines}"

    await send_text(bot, chat_id, reply)

    # 6. Send Excel file ─────────────────────────────────────────────────────
    excel_sent = await send_document(
        bot=bot,
        chat_id=chat_id,
        file_path=result.excel_path,
        caption=f"📊 Excel — {result.filename}",
    )
    if excel_sent:
        logger.info("Excel sent to chat_id=%s: %s", chat_id, result.filename)
    else:
        logger.error("Failed to send Excel to chat_id=%s", chat_id)
        await send_text(
            bot, chat_id,
            "⚠️ Excel file generated but could not be sent.\n"
            "Check the Quotation folder on the PC.",
        )

    # 7. Send PDF file (non-fatal if missing or failed) ──────────────────────
    if result.pdf_status == "created" and result.pdf_path:
        pdf_sent = await send_document(
            bot=bot,
            chat_id=chat_id,
            file_path=result.pdf_path,
            caption=f"📄 PDF — {result.filename.replace('.xlsx', '.pdf')}",
        )
        if pdf_sent:
            logger.info("PDF sent to chat_id=%s", chat_id)
        else:
            logger.error("Failed to send PDF to chat_id=%s", chat_id)
            await send_text(bot, chat_id, "⚠️ PDF was generated but could not be sent via Telegram.")
    else:
        logger.info(
            "PDF not sent to chat_id=%s — status=%s message=%s",
            chat_id, result.pdf_status, result.pdf_message,
        )
