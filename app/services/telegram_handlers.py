"""
services/telegram_handlers.py — Strict first-word message routing.

Routing table (first word wins; quotation is explicit, never a catch-all):
  help / /start / /help           → _handle_help
  create  + second-word=ledger    → _handle_create_ledger
  add     + second-word=ledger    → _handle_add_debit
  ledger | balance | outstanding  → _handle_ledger
  payment received …              → _handle_payment
  quote | quotation | qtn | qt    → _handle_quotation
  anything else                   → unknown-command reply

Ledger and quotation share NO code paths.
"""

import os
import re as _re
import logging
import tempfile
from datetime import date as _date
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.services.command_parser import parse_quotation_command
from app.services.company_memory import lookup as company_lookup, resolve_company_name
from app.schemas.quotation import QuotationCreateRequest, QuotationItem
from app.services.quotation_service import create_quotation
from app.services.telegram_sender import send_text, send_document

logger = logging.getLogger(__name__)

# ── Month name → number map (for statement command) ───────────────────────────
_MONTH_MAP: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_STMT_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# ── Pending OCR state  (chat_id → extracted fields) ──────────────────────────
# Keys per entry: company, invoice, date, amount, lpo
_pending_ocr: dict[int, dict] = {}

# ── Compiled patterns ─────────────────────────────────────────────────────────

# payment received for COMPANY invoice NUMBER amount AMOUNT
_PAY_RE = _re.compile(
    r"payment\s+received\s+(?:for\s+|from\s+)?"
    r"(?P<company>.+?)\s+"
    r"(?:invoice|inv)\s*#?\s*(?P<invoice>\S+)\s+"
    r"(?:amount|amt|aed|dhs?)?\s*(?P<amount>[\d,]+(?:\.\d{1,2})?)",
    _re.I,
)

# add ledger COMPANY invoice NUMBER debit AMOUNT
_ADD_DEBIT_RE = _re.compile(
    r"add\s+ledger\s+(?P<company>.+?)\s+"
    r"(?:invoice|inv)\s*#?\s*(?P<invoice>\S+)\s+"
    r"(?:debit|amount|amt)\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)",
    _re.I,
)

# create ledger for COMPANY  (or  create ledger COMPANY)
_CREATE_LEDGER_RE = _re.compile(
    r"create\s+ledger\s+(?:for\s+)?(?P<company>.+)",
    _re.I,
)

# optional LPO anywhere in the command: "lpo 12345" or "lpo no 12345"
_LPO_RE = _re.compile(r"\blpo\s+(?:no\.?\s+)?(?P<lpo>\S+)", _re.I)

# OCR correction: "correct invoice 1234"  /  "correct company gulf"
_CORRECT_RE = _re.compile(
    r"correct\s+(?P<field>invoice|date|amount|lpo|company)\s+(?P<value>.+)",
    _re.I,
)

# optional date anywhere in the command: "date DD-MM-YYYY" or "date YYYY-MM-DD"
_DATE_RE = _re.compile(
    r"\bdate\s+(?P<date>\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})\b",
    _re.I,
)


def _extract_date(text: str) -> str:
    """Return the date from 'date DD-MM-YYYY' / 'date YYYY-MM-DD' in text,
    or today's date as DD-MM-YYYY if not present."""
    m = _DATE_RE.search(text)
    if m:
        return m.group("date")
    return _date.today().strftime("%d-%m-%Y")

# ── Help text ─────────────────────────────────────────────────────────────────

_HELP = (
    "👋 <b>OfficePilot AI — Commands</b>\n\n"
    "<b>── Quotation ──</b>\n"
    "<pre>make quotation for COMPANY\n"
    "item 1: description, qty 2, price 500 each\n"
    "item 2: description, qty 1, price 300 each</pre>\n"
    "<pre>make quotation for COMPANY item 1 desc qty 2 price 500 each item 2 desc qty 1 price 300</pre>\n"
    "<pre>quote for COMPANY description qty 1 rate 500</pre>\n\n"
    "<b>── Ledger ──</b>\n"
    "<pre>create ledger for gulf</pre>\n"
    "<pre>ledger gulf</pre>\n"
    "<pre>balance quant</pre>\n"
    "<pre>outstanding islami</pre>\n"
    "<pre>add ledger gulf invoice 1234 debit 5000</pre>\n"
    "<pre>payment received for gulf invoice 1234 amount 5000</pre>\n\n"
    "<b>── Account Statement ──</b>\n"
    "<pre>statement gulf april 2026</pre>\n"
    "<pre>statement gulf 04 2026 unpaid</pre>\n"
    "<pre>statement gulf april 2026 pdf</pre>\n\n"
    "<b>── Documents ──</b>\n"
    "<pre>send trade license</pre>\n"
    "<pre>send shed contract</pre>\n"
    "<pre>send municipality</pre>\n\n"
    "<i>Short aliases: gulf, islami, quant, globol, tayseer arar, tayseer containers</i>"
)

_UNAUTHORIZED = "⛔ Unauthorized."


# ── Security ──────────────────────────────────────────────────────────────────

def _is_allowed(chat_id: int) -> bool:
    allowed = settings.telegram_allowed_ids
    return bool(allowed) and chat_id in allowed


# ── Entry point ───────────────────────────────────────────────────────────────

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message is None or update.message.text is None:
        return

    chat_id = update.message.chat_id
    text    = update.message.text.strip()

    if not _is_allowed(chat_id):
        logger.warning("Rejected chat_id=%s", chat_id)
        await send_text(context.bot, chat_id, _UNAUTHORIZED)
        return

    bot = context.bot

    # ── Pending OCR confirmation ───────────────────────────────────────────────
    if chat_id in _pending_ocr:
        tl = text.lower().strip()
        if tl in ("yes", "ok", "confirm", "y"):
            await _confirm_ocr(chat_id, bot)
            return
        if tl in ("no", "cancel", "nope", "n"):
            del _pending_ocr[chat_id]
            await send_text(bot, chat_id, "❌ OCR entry cancelled.")
            return
        if tl.startswith("correct "):
            await _apply_correction(text, chat_id, bot)
            return
        # Otherwise fall through to normal routing

    first_word = text.strip().lower().split()[0] if text.strip() else ""
    t = text.lower()

    print("ROUTE:", first_word, flush=True)
    logger.info("ROUTE: %r  full=%.80r", first_word, text)

    if first_word in ("help", "/help", "/start"):
        await send_text(bot, chat_id, _HELP)
        return

    if first_word == "create":
        if t.startswith("create ledger"):
            try:
                await _handle_create_ledger(text, chat_id, bot)
            except Exception as exc:
                logger.exception("create ledger error")
                await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        else:
            await send_text(bot, chat_id, "❌ Invalid command. Send <b>help</b>.")
        return

    if first_word in ("ledger", "balance", "outstanding"):
        try:
            await _handle_ledger(text, chat_id, bot)
        except Exception as exc:
            logger.exception("ledger error")
            await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        return

    if t.startswith("payment received"):
        try:
            await _handle_payment(text, chat_id, bot)
        except Exception as exc:
            logger.exception("payment error")
            await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        return

    if first_word == "add":
        if t.startswith("add ledger"):
            try:
                await _handle_add_debit(text, chat_id, bot)
            except Exception as exc:
                logger.exception("add ledger error")
                await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        else:
            await send_text(bot, chat_id, "❌ Invalid command. Send <b>help</b>.")
        return

    if first_word == "make":
        if _re.match(r"make\s+(?:quotation|quote)\s+for\b", t):
            try:
                await _handle_nl_quotation(text, chat_id, context)
            except Exception as exc:
                logger.exception("NL quotation error")
                await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        else:
            await send_text(bot, chat_id, "❌ Invalid command. Send <b>help</b>.")
        return

    if first_word == "send":
        try:
            await _handle_send_doc(text, chat_id, bot)
        except Exception as exc:
            logger.exception("send doc error")
            await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        return

    if first_word == "statement":
        try:
            await _handle_statement(text, chat_id, bot)
        except Exception as exc:
            logger.exception("statement error")
            await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        return

    if first_word in ("quote", "quotation"):
        # NL format detected by presence of "item N" blocks
        if _re.search(r"\bitem\s*\d+\b", text, _re.I):
            try:
                await _handle_nl_quotation(text, chat_id, context)
            except Exception as exc:
                logger.exception("NL quotation error")
                await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")
        else:
            await _handle_quotation(text, chat_id, context)
        return

    await send_text(bot, chat_id, "❌ Invalid command. Send <b>help</b> for usage.")


async def _safe(bot, chat_id: int, coro):
    """Await coro; catch and report any exception to Telegram."""
    try:
        await coro
    except Exception as exc:
        logger.exception("Handler error")
        await send_text(bot, chat_id, f"❌ Error:\n<code>{exc}</code>")


# ── Create ledger handler ─────────────────────────────────────────────────────

async def _handle_create_ledger(text: str, chat_id: int, bot) -> None:
    from app.services.ledger_excel import create_ledger, ledger_exists

    m = _CREATE_LEDGER_RE.match(text.strip())
    if not m:
        await send_text(bot, chat_id,
            "❌ Format: <pre>create ledger for COMPANY</pre>")
        return

    raw = m.group("company").strip()
    company = resolve_company_name(raw)
    logger.info("Create ledger: %r → %r", raw, company)

    if ledger_exists(company):
        await send_text(bot, chat_id,
            f"ℹ️ Ledger already exists for <b>{company}</b>")
        return

    create_ledger(company)
    await send_text(bot, chat_id,
        f"✅ Ledger created for <b>{company}</b>")


# ── Add debit handler ─────────────────────────────────────────────────────────

async def _handle_add_debit(text: str, chat_id: int, bot) -> None:
    from app.services.ledger_excel import add_debit_row, ledger_exists

    m = _ADD_DEBIT_RE.search(text)
    if not m:
        await send_text(bot, chat_id,
            "❌ Format:\n"
            "<pre>add ledger COMPANY invoice NUMBER debit AMOUNT</pre>")
        return

    raw     = m.group("company").strip()
    inv_no  = m.group("invoice").strip()
    amount  = float(m.group("amount").replace(",", ""))
    company = resolve_company_name(raw)
    logger.info("Add debit: %r → %r  inv=%s  amount=%.2f", raw, company, inv_no, amount)

    if not ledger_exists(company):
        await send_text(bot, chat_id,
            f"❌ No ledger found for <b>{company}</b>.\n"
            f"Create it first:\n<pre>create ledger for {raw}</pre>")
        return

    entry_date = _extract_date(text)
    lpo_m = _LPO_RE.search(text)
    lpo_no = lpo_m.group("lpo").strip() if lpo_m else None
    description = f"LPO {lpo_no}" if lpo_no else "Entry"

    add_debit_row(company, inv_no, amount, description=description, date_str=entry_date)
    reply = (
        f"✅ <b>Debit added</b>\n\n"
        f"Company: <b>{company}</b>\n"
        f"Invoice: <code>{inv_no}</code>\n"
        f"Amount:  <b>AED {amount:,.2f}</b>\n"
        f"Date:    <code>{entry_date}</code>"
    )
    if lpo_no:
        reply += f"\nLPO:     <code>{lpo_no}</code>"
    await send_text(bot, chat_id, reply)


# ── Payment (credit) handler ──────────────────────────────────────────────────

async def _handle_payment(text: str, chat_id: int, bot) -> None:
    from app.services.ledger_excel import add_credit_row, ledger_exists, get_ledger_summary

    m = _PAY_RE.search(text)
    if not m:
        await send_text(bot, chat_id,
            "❌ Format:\n"
            "<pre>payment received for COMPANY invoice NUMBER amount AMOUNT</pre>")
        return

    raw     = m.group("company").strip()
    inv_no  = m.group("invoice").strip()
    amount  = float(m.group("amount").replace(",", ""))
    company = resolve_company_name(raw)
    logger.info("Payment: %r → %r  inv=%s  amount=%.2f", raw, company, inv_no, amount)

    if not ledger_exists(company):
        await send_text(bot, chat_id,
            f"❌ No ledger found for <b>{company}</b>.\n"
            f"Create it first:\n<pre>create ledger for {raw}</pre>")
        return

    entry_date = _extract_date(text)
    add_credit_row(company, inv_no, amount, date_str=entry_date)
    summary = get_ledger_summary(company)
    outstanding = summary["outstanding"] if summary else 0.0

    await send_text(bot, chat_id,
        f"✅ <b>Payment recorded</b>\n\n"
        f"Company: <b>{company}</b>\n"
        f"Invoice: <code>{inv_no}</code>\n"
        f"Amount:  <b>AED {amount:,.2f}</b>\n"
        f"Date:    <code>{entry_date}</code>\n\n"
        f"Outstanding balance: <b>AED {outstanding:,.2f}</b>")


# ── Ledger query handler ──────────────────────────────────────────────────────

async def _handle_ledger(text: str, chat_id: int, bot) -> None:
    from app.services.ledger_excel import get_ledger_summary, ledger_exists

    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await send_text(bot, chat_id,
            "❌ Format: <pre>ledger COMPANY</pre>")
        return

    tail = parts[1].strip()
    if tail.lower().startswith("for "):
        tail = tail[4:].strip()

    raw     = tail
    company = resolve_company_name(raw)
    logger.info("Ledger query: %r → %r", raw, company)

    if not ledger_exists(company):
        await send_text(bot, chat_id,
            f"ℹ️ No ledger found for <b>{company}</b>.\n"
            f"Create it first:\n<pre>create ledger for {raw}</pre>")
        return

    summary = get_ledger_summary(company)
    if not summary or not summary["rows"]:
        await send_text(bot, chat_id,
            f"📊 <b>{company}</b>\n\nLedger exists but has no entries yet.")
        return

    lines = []
    for r in summary["rows"][-10:]:
        if r["debit"]:
            lines.append(f"📤 <code>{r['invoice']}</code>  Debit: AED {r['debit']:,.0f}")
        elif r["credit"]:
            lines.append(f"📥 <code>{r['invoice']}</code>  Credit: AED {r['credit']:,.0f}")

    await send_text(bot, chat_id,
        f"📊 <b>{company}</b>\n\n"
        f"Total Invoiced:  AED {summary['total_debit']:,.2f}\n"
        f"Total Received:  AED {summary['total_credit']:,.2f}\n"
        f"<b>Outstanding: AED {summary['outstanding']:,.2f}</b>\n\n"
        + "\n".join(lines))


# ── Quotation handler ─────────────────────────────────────────────────────────

async def _handle_quotation(
    text: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    bot = context.bot

    try:
        parsed_resp = parse_quotation_command(text)
    except Exception as exc:
        logger.exception("Parser crashed")
        await send_text(bot, chat_id, f"❌ Parse error:\n<code>{exc}</code>")
        return

    if not parsed_resp.success or parsed_resp.parsed is None:
        await send_text(bot, chat_id,
            "❌ Could not parse quotation.\n\n"
            "Try:\n<pre>quote for CLIENT description qty 1 rate NNN</pre>")
        return

    p = parsed_resp.parsed

    # Resolve alias → canonical name, enrich with company memory
    canonical = resolve_company_name(p.client_name)
    attn = trn = phone = fax = ""
    matches = company_lookup(canonical, max_results=1)
    if matches:
        best = matches[0]
        attn, trn, phone, fax = best.attn, best.trn, best.phone, best.fax
        p.client_name = best.company_name

    today = _date.today()
    items = [
        QuotationItem(
            description=it.description, size=it.size,
            quantity=it.quantity, rate=it.rate, amount=it.amount,
        )
        for it in p.items
    ]

    req = QuotationCreateRequest(
        year=p.year or str(today.year),
        month=p.month or str(today.month).zfill(2),
        date=p.date or today.strftime("%d-%m-%Y"),
        client_name=p.client_name,
        items=items, attn=attn, trn=trn, phone=phone, fax=fax,
        description=p.description, size=p.size,
        quantity=p.quantity, rate=p.rate, tax=p.tax, total=p.total,
    )

    try:
        result = create_quotation(req)
    except Exception as exc:
        logger.exception("Quotation creation failed")
        await send_text(bot, chat_id, f"❌ Quotation failed:\n<code>{exc}</code>")
        return

    ref_str = f"{req.year}/{req.month}/{result.new_ref_number:04d}"
    pdf_line = "📄 PDF: ready" if result.pdf_status == "created" else "📄 PDF: not available"
    reply = (
        "✅ <b>Quotation Created</b>\n\n"
        f"Client: <b>{p.client_name}</b>\n"
        f"Ref No: <code>{ref_str}</code>\n"
        f"Total:  <b>AED {req.total:,.2f}</b>\n"
        f"File:   <code>{result.filename}</code>\n"
        f"{pdf_line}"
    )
    if parsed_resp.warnings:
        reply += "\n\n⚠️ <i>Notes:</i>\n" + "\n".join(f"• {w}" for w in parsed_resp.warnings[:3])

    await send_text(bot, chat_id, reply)

    if result.pdf_status == "created" and result.pdf_path:
        if await send_document(bot, chat_id, result.pdf_path,
                               f"📄 {result.filename.replace('.xlsx', '.pdf')}"):
            return

    await send_document(bot, chat_id, result.excel_path, f"📊 {result.filename}")


# ── OCR helpers ───────────────────────────────────────────────────────────────

def _fmt_pending(p: dict) -> str:
    amt = f"AED {p['amount']:,.2f}" if p.get("amount") is not None else "(not detected)"
    return (
        "📋 <b>Extracted Invoice Data</b>\n\n"
        f"Company: <b>{p.get('company') or '(not detected)'}</b>\n"
        f"Invoice: <code>{p.get('invoice') or '(not detected)'}</code>\n"
        f"Date:    <code>{p.get('date') or '(not detected)'}</code>\n"
        f"Amount:  <b>{amt}</b>\n"
        f"LPO:     <code>{p.get('lpo') or '(none)'}</code>"
    )


async def _confirm_ocr(chat_id: int, bot) -> None:
    from app.services.ledger_excel import add_debit_row, ledger_exists
    p = _pending_ocr[chat_id]

    missing = [f for f in ("company", "invoice", "amount") if not p.get(f)]
    if missing:
        fields_str = ", ".join(missing)
        await send_text(bot, chat_id,
            f"⚠️ Still missing: <b>{fields_str}</b>\n"
            "Use:\n<pre>correct FIELD VALUE</pre>")
        return

    company  = p["company"]
    invoice  = p["invoice"]
    amount   = float(p["amount"])
    date_str = p.get("date") or _date.today().strftime("%d-%m-%Y")
    lpo      = p.get("lpo")
    desc     = f"LPO {lpo}" if lpo else "Entry"

    if not ledger_exists(company):
        await send_text(bot, chat_id,
            f"❌ No ledger for <b>{company}</b>.\n"
            f"Create it first: <pre>create ledger for {company}</pre>")
        return

    add_debit_row(company, invoice, amount, description=desc, date_str=date_str)
    del _pending_ocr[chat_id]

    reply = (
        "✅ <b>Ledger entry added from OCR</b>\n\n"
        f"Company: <b>{company}</b>\n"
        f"Invoice: <code>{invoice}</code>\n"
        f"Amount:  <b>AED {amount:,.2f}</b>\n"
        f"Date:    <code>{date_str}</code>"
    )
    if lpo:
        reply += f"\nLPO:     <code>{lpo}</code>"
    await send_text(bot, chat_id, reply)


async def _apply_correction(text: str, chat_id: int, bot) -> None:
    m = _CORRECT_RE.match(text.strip())
    if not m:
        await send_text(bot, chat_id,
            "❌ Format: <pre>correct FIELD VALUE</pre>\n"
            "Fields: invoice · date · amount · lpo · company")
        return

    field = m.group("field").lower()
    value = m.group("value").strip()
    p     = _pending_ocr[chat_id]

    if field == "amount":
        try:
            p["amount"] = float(value.replace(",", ""))
        except ValueError:
            await send_text(bot, chat_id, f"❌ Invalid amount: <code>{value}</code>")
            return
    elif field == "company":
        p["company"] = resolve_company_name(value)
    else:
        p[field] = value

    await send_text(bot, chat_id,
        _fmt_pending(p) +
        "\n\nReply <b>YES</b> to confirm or <b>NO</b> to cancel.")


# ── File / OCR handler (called for photo and document messages) ───────────────

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    chat_id = update.message.chat_id
    if not _is_allowed(chat_id):
        await send_text(context.bot, chat_id, _UNAUTHORIZED)
        return

    bot = context.bot
    await send_text(bot, chat_id, "🔍 Processing file with OCR…")

    tmp_path = None
    try:
        if update.message.photo:
            tg_file = await update.message.photo[-1].get_file()
            suffix  = ".jpg"
        elif update.message.document:
            doc     = update.message.document
            suffix  = Path(doc.file_name).suffix if doc.file_name else ".bin"
            tg_file = await doc.get_file()
        else:
            await send_text(bot, chat_id, "❌ Unsupported file type.")
            return

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name

        await tg_file.download_to_drive(tmp_path)
        logger.info("OCR file downloaded: %s  (%s)", tmp_path, suffix)

        from app.services.ocr_parser import extract_from_file
        _raw_text, fields = extract_from_file(tmp_path)

        _pending_ocr[chat_id] = fields
        logger.info("OCR fields for chat_id=%s: %s", chat_id, fields)

        reply = (
            _fmt_pending(fields) +
            "\n\nReply <b>YES</b> to add to ledger, <b>NO</b> to cancel.\n"
            "Or correct any field:\n"
            "<pre>correct invoice NUMBER\n"
            "correct date DD-MM-YYYY\n"
            "correct amount NUMBER\n"
            "correct lpo NUMBER\n"
            "correct company NAME</pre>"
        )
        await send_text(bot, chat_id, reply)

    except Exception as exc:
        logger.exception("OCR processing failed for chat_id=%s", chat_id)
        await send_text(bot, chat_id,
            f"❌ OCR failed:\n<code>{exc}</code>\n\n"
            "Make sure pytesseract and Tesseract are installed.")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Natural-language quotation ────────────────────────────────────────────────

_NL_HDR_RE     = _re.compile(
    r"(?:make\s+)?(?:quotation|quote)\s+for\s+(.+?)(?=\s+item\s*\d+\b|\n|$)",
    _re.I,
)
_ITEM_SPLIT_RE = _re.compile(r"\bitem\s*\d+\s*:?\s*", _re.I)


def _parse_item_text(item_text: str) -> "dict | None":
    """
    Extract {description, qty, rate, amount} from one item block.
    Handles: "desc, qty 2, price 50 each" / "desc qty 2 rate 50" / "desc 50 each"
    """
    text = item_text.strip().rstrip(",")

    qty_m = _re.search(r"\bq(?:ty|uantity)\s+(\d+(?:\.\d+)?)", text, _re.I)
    qty   = float(qty_m.group(1)) if qty_m else 1.0

    rate_m = _re.search(r"\b(?:price|rate|each)\s+(\d+(?:\.\d+)?)", text, _re.I)
    if not rate_m:
        rate_m = _re.search(r"(\d+(?:\.\d+)?)\s+(?:each|aed|dhs?)\b", text, _re.I)
    rate = float(rate_m.group(1)) if rate_m else 0.0

    # Description = everything before the first keyword marker
    desc_end = len(text)
    for m in filter(None, [qty_m, rate_m]):
        if m.start() < desc_end:
            desc_end = m.start()
    description = _re.sub(r"[,\s]+$", "", text[:desc_end]).strip()

    return {
        "description": description,
        "qty":    qty,
        "rate":   rate,
        "amount": round(qty * rate, 2),
    } if description else None


def _parse_nl_quotation(text: str) -> "dict | None":
    """
    Parse natural-language quotation request.
    Returns {company, items:[{description,qty,rate,amount}]} or None.
    """
    m = _NL_HDR_RE.match(text.strip())
    if not m:
        return None
    company = m.group(1).strip().rstrip(",")
    if not company:
        return None

    parts = _ITEM_SPLIT_RE.split(text)   # parts[0]=header area, parts[1:]=items
    items = [it for part in parts[1:] if (it := _parse_item_text(part))]
    return {"company": company, "items": items} if items else None


async def _handle_nl_quotation(
    text: str,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    bot = context.bot

    nl = _parse_nl_quotation(text)
    if not nl or not nl["items"]:
        await send_text(bot, chat_id,
            "❌ Could not parse items. Format:\n"
            "<pre>make quotation for COMPANY\n"
            "item 1: description, qty N, price N each\n"
            "item 2: description, qty N, price N each</pre>")
        return

    raw_company = nl["company"]
    canonical   = resolve_company_name(raw_company)
    attn = trn = phone = fax = ""
    matches = company_lookup(canonical, max_results=1)
    if matches:
        best      = matches[0]
        attn, trn, phone, fax = best.attn, best.trn, best.phone, best.fax
        canonical = best.company_name

    today    = _date.today()
    subtotal = sum(it["amount"] for it in nl["items"])
    tax      = round(subtotal * 0.05, 2)
    total    = round(subtotal + tax, 2)

    items = [
        QuotationItem(
            description=it["description"],
            size="",
            quantity=it["qty"],
            rate=it["rate"],
            amount=it["amount"],
        )
        for it in nl["items"]
    ]

    req = QuotationCreateRequest(
        year=str(today.year),
        month=str(today.month).zfill(2),
        date=today.strftime("%d-%m-%Y"),
        client_name=canonical,
        items=items,
        attn=attn, trn=trn, phone=phone, fax=fax,
        description=items[0].description,
        size=items[0].size,
        quantity=items[0].quantity,
        rate=items[0].rate,
        tax=tax,
        total=total,
    )

    try:
        result = create_quotation(req)
    except Exception as exc:
        logger.exception("NL quotation creation failed")
        await send_text(bot, chat_id, f"❌ Quotation failed:\n<code>{exc}</code>")
        return

    ref_str   = f"{req.year}/{req.month}/{result.new_ref_number:04d}"
    pdf_line  = "📄 PDF: ready" if result.pdf_status == "created" else "📄 PDF: not available"
    item_lines = "\n".join(
        f"  {i+1}. {it.description}  ×{int(it.quantity)}  @ AED {it.rate:,.2f}"
        for i, it in enumerate(items)
    )

    reply = (
        "✅ <b>Quotation Created</b>\n\n"
        f"Client: <b>{canonical}</b>\n"
        f"Ref No: <code>{ref_str}</code>\n\n"
        f"Items:\n{item_lines}\n\n"
        f"Subtotal: AED {subtotal:,.2f}\n"
        f"VAT 5%:   AED {tax:,.2f}\n"
        f"Total:    <b>AED {total:,.2f}</b>\n"
        f"{pdf_line}"
    )
    await send_text(bot, chat_id, reply)

    if result.pdf_status == "created" and result.pdf_path:
        if await send_document(bot, chat_id, result.pdf_path,
                               f"📄 {result.filename.replace('.xlsx', '.pdf')}"):
            return
    await send_document(bot, chat_id, result.excel_path, f"📊 {result.filename}")


# ── Document fetch ────────────────────────────────────────────────────────────

async def _handle_send_doc(text: str, chat_id: int, bot) -> None:
    from app.services.file_fetcher import search_docs, DOCS_FOLDER

    parts = text.strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await send_text(bot, chat_id,
            "❌ Format: <pre>send DOCUMENT NAME</pre>\n"
            "Example: <pre>send trade license</pre>")
        return

    query   = parts[1].strip()
    matches = search_docs(query)

    if not matches:
        await send_text(bot, chat_id,
            f"❌ No file found matching <b>{query}</b> in the documents folder.")
        return

    if len(matches) == 1:
        f = matches[0]
        await send_text(bot, chat_id, f"📎 Sending: <b>{f.name}</b>")
        await send_document(bot, chat_id, str(f), f.name)
        return

    # Multiple matches — list options
    names = "\n".join(f"• {m.name}" for m in matches[:10])
    await send_text(bot, chat_id,
        f"📂 Multiple files found for <b>{query}</b>:\n\n{names}\n\n"
        "Please be more specific.")


# ── Account statement ─────────────────────────────────────────────────────────

def _parse_statement_cmd(text: str) -> "dict | None":
    """
    Parse: statement <company> <month> <year> [unpaid|full|pdf]
    month can be a name (april) or number (04 / 4).
    company may be multi-word (tayseer arar).
    Returns {company_raw, month, year, mode} or None.
    """
    tokens = text.strip().split()
    if not tokens or tokens[0].lower() != "statement":
        return None

    rest = list(tokens[1:])   # mutable working copy

    # Optional trailing mode flag
    mode = "full"
    if rest and rest[-1].lower() in ("unpaid", "full", "pdf"):
        mode = rest.pop().lower()

    # Year: last 4-digit 20XX token (scan right-to-left)
    year = None
    for i in range(len(rest) - 1, -1, -1):
        if _re.match(r"^20[2-3]\d$", rest[i]):
            year = int(rest.pop(i))
            break

    # Month: last remaining token that is a name or 1-2 digit number
    month = None
    if rest:
        last = rest[-1].lower()
        if last in _MONTH_MAP:
            month = _MONTH_MAP[last]
            rest.pop()
        elif _re.match(r"^0?([1-9]|1[0-2])$", last):
            month = int(last)
            rest.pop()

    if not year or not month or not rest:
        return None

    return {"company_raw": " ".join(rest), "month": month, "year": year, "mode": mode}


async def _handle_statement(text: str, chat_id: int, bot) -> None:
    from app.services.statement_excel import generate_statement, statement_summary_text

    parsed = _parse_statement_cmd(text)
    if not parsed:
        await send_text(bot, chat_id,
            "❌ Format:\n"
            "<pre>statement COMPANY MONTH YEAR [unpaid|full|pdf]</pre>\n\n"
            "Examples:\n"
            "<pre>statement gulf april 2026\n"
            "statement gulf 04 2026 unpaid\n"
            "statement gulf april 2026 pdf</pre>")
        return

    company = resolve_company_name(parsed["company_raw"])
    month   = parsed["month"]
    year    = parsed["year"]
    mode    = parsed["mode"]

    month_name = _STMT_MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
    await send_text(bot, chat_id,
        f"📊 Generating <b>{company}</b> statement for {month_name} {year}…")

    try:
        from app.services.ledger_excel import get_ledger_summary
        summary = get_ledger_summary(company)
        if not summary:
            await send_text(bot, chat_id,
                f"❌ No ledger found for <b>{company}</b>.\n"
                f"Create it first: <pre>create ledger for {parsed['company_raw']}</pre>")
            return

        xlsx_path, pdf_path = generate_statement(company, month, year, mode)
    except FileNotFoundError:
        await send_text(bot, chat_id,
            f"❌ No ledger found for <b>{company}</b>.\n"
            f"Create it first: <pre>create ledger for {parsed['company_raw']}</pre>")
        return
    except Exception as exc:
        logger.exception("Statement generation failed")
        await send_text(bot, chat_id, f"❌ Error generating statement:\n<code>{exc}</code>")
        return

    # Re-read for summary text
    summary = get_ledger_summary(company)
    from app.services.statement_excel import _parse_date as _stmt_parse_date
    opening = sum(
        r["debit"] - r["credit"]
        for r in (summary["rows"] if summary else [])
        if (d := _stmt_parse_date(r.get("date", ""))) and (d.year < year or (d.year == year and d.month < month))
    )
    period_rows = [
        r for r in (summary["rows"] if summary else [])
        if (d := _stmt_parse_date(r.get("date", ""))) and d.year == year and d.month == month
    ]
    closing = opening + sum(r["debit"] - r["credit"] for r in period_rows)

    caption = statement_summary_text(company, month, year, opening, closing, len(period_rows))
    await send_text(bot, chat_id, caption)

    if pdf_path:
        await send_document(bot, chat_id, str(pdf_path), f"📄 {pdf_path.name}")
    else:
        await send_document(bot, chat_id, str(xlsx_path), f"📊 {xlsx_path.name}")
