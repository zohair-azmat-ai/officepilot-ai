"""
services/invoice_service.py — Invoice creation orchestrator.

Handles:
  • Invoice number generation (INV-YYYY-XXXX, sequential per month folder)
  • Auto monthly folder rollover (always uses today's system date)
  • Excel template fill via invoice_writer
  • PDF export via pdf_export
"""

import logging
import re
from datetime import date as _date
from pathlib import Path

from app.config import settings
from app.services.file_naming import sanitize_client_name, sanitize_date
from app.services.invoice_writer import InvoiceItem, InvoiceRequest, fill_invoice_template
from app.services.pdf_export import export_to_pdf

logger = logging.getLogger(__name__)

# Matches "INV-2026-0105" in a filename — captures the sequence number
_INV_SEQ_RE = re.compile(r"INV-\d{4}-(\d+)", re.IGNORECASE)


def _next_invoice_seq(folder: Path) -> int:
    """Scan folder for highest existing INV-YYYY-XXXX sequence, return next."""
    max_seq = 0
    if folder.exists():
        for entry in folder.iterdir():
            if entry.is_file() and entry.suffix.lower() in {".xlsx", ".pdf"}:
                m = _INV_SEQ_RE.search(entry.name)
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def create_invoice(
    client_name: str,
    items: list[dict],   # each: {description, quantity, rate}
    lpo:   str = "",
    do_no: str = "",
    attn:  str = "",
    trn:   str = "",
) -> dict:
    """
    Create a complete invoice: fill template → export PDF → return result dict.

    Parameters
    ----------
    client_name : str  — company/client name
    items       : list — dicts with keys description, quantity, rate
    lpo         : str  — LPO / purchase-order number (optional)
    do_no       : str  — delivery-order number (optional)
    attn        : str  — attention / contact name (optional)
    trn         : str  — tax registration number (optional)

    Returns
    -------
    dict with keys:
        invoice_no, client_name, excel_path, pdf_path, pdf_status,
        subtotal, tax, total, items_count, filename
    """
    today = _date.today()
    year  = today.year
    month = today.month

    # ── Folder — always derived from today's date ──────────────────────────────
    folder = Path(settings.INVOICE_BASE_PATH) / str(year) / str(month).zfill(2)
    folder.mkdir(parents=True, exist_ok=True)
    logger.info("Invoice folder: %s", folder)

    # ── Invoice number ─────────────────────────────────────────────────────────
    seq        = _next_invoice_seq(folder)
    invoice_no = f"INV-{year}-{seq:04d}"
    logger.info("Invoice number: %s", invoice_no)

    # ── Build items + totals ───────────────────────────────────────────────────
    inv_items = []
    subtotal  = 0.0
    for it in items:
        qty    = float(it.get("quantity", 1))
        rate   = float(it.get("rate", 0))
        amount = round(qty * rate, 2)
        subtotal += amount
        inv_items.append(InvoiceItem(
            description=str(it.get("description", "")),
            quantity=qty,
            rate=rate,
            amount=amount,
        ))

    subtotal = round(subtotal, 2)
    tax      = round(subtotal * 0.05, 2)
    total    = round(subtotal + tax, 2)

    date_str = today.strftime("%d-%m-%Y")

    request = InvoiceRequest(
        client_name=client_name,
        date=date_str,
        invoice_no=invoice_no,
        year=str(year),
        month=str(month).zfill(2),
        lpo=lpo,
        do_no=do_no,
        attn=attn,
        trn=trn,
        items=inv_items,
        tax=tax,
        total=total,
    )

    # ── File paths ─────────────────────────────────────────────────────────────
    safe_client = sanitize_client_name(client_name)
    safe_date   = sanitize_date(date_str)
    stem        = f"{safe_date} {invoice_no} {safe_client}"
    excel_path  = folder / f"{stem}.xlsx"
    pdf_path_expected = folder / f"{stem}.pdf"

    # ── Write Excel ────────────────────────────────────────────────────────────
    fill_invoice_template(request, excel_path)
    logger.info("Invoice Excel written: %s", excel_path)

    # ── Export PDF ─────────────────────────────────────────────────────────────
    pdf_result = export_to_pdf(excel_path)
    logger.info("Invoice PDF: %s — %s", pdf_result["status"], pdf_result["message"])

    return {
        "invoice_no":  invoice_no,
        "client_name": client_name,
        "excel_path":  str(excel_path),
        "pdf_path":    pdf_result["pdf_path"],
        "pdf_status":  pdf_result["status"],
        "subtotal":    subtotal,
        "tax":         tax,
        "total":       total,
        "items_count": len(inv_items),
        "filename":    excel_path.name,
    }
