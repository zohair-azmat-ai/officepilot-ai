"""
services/invoice_service.py — Invoice creation orchestrator.

Handles:
  • Company-specific template selection (quant_gulf / gulf_extrusions)
  • Invoice number generation — sequential plain integer, scanned from folder
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
from app.services.invoice_writer import (
    InvoiceItem, InvoiceRequest, fill_invoice_template, _LAYOUTS,
)
from app.services.pdf_export import export_to_pdf

logger = logging.getLogger(__name__)

# Matches a 4+-digit number at the end of a filename (before .xlsx/.pdf)
_SEQ_RE = re.compile(r"(\d{4,})\.(?:xlsx|pdf)$", re.IGNORECASE)


def _next_invoice_seq(base_path: Path, seq_keyword: str, seq_floor: int) -> int:
    """
    Scan base_path recursively for invoice files belonging to this company,
    return the next sequential number (max found, or seq_floor, whichever is higher, + 1).
    """
    max_seq = seq_floor
    if base_path.exists():
        for entry in base_path.rglob("*.xlsx"):
            if seq_keyword.lower() not in entry.stem.lower():
                continue
            m = _SEQ_RE.search(entry.name)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def create_invoice(
    company_key: str,
    client_name: str,
    items: list[dict],   # each: {description, quantity, rate}
    lpo:               str = "",
    do_no:             str = "",
    attn:              str = "",
    trn:               str = "",
    forced_invoice_no: "int | None" = None,
) -> dict:
    """
    Create a complete invoice for the given company: fill template → export PDF.

    Parameters
    ----------
    company_key  : str  — "quant_gulf" or "gulf_extrusions"
    client_name  : str  — company/client name (for display in reply)
    items        : list — dicts with keys description, quantity, rate
    lpo          : str  — LPO / purchase-order number (optional)
    do_no        : str  — delivery-order number (optional)
    attn         : str  — attention / contact name (optional)
    trn          : str  — tax registration number (optional)

    Returns
    -------
    dict with keys:
        invoice_no, client_name, excel_path, pdf_path, pdf_status,
        subtotal, tax, total, items_count, filename
    """
    layout = _LAYOUTS.get(company_key)
    if layout is None:
        raise ValueError(
            f"Unknown company_key: {company_key!r}. "
            "Use 'quant_gulf' or 'gulf_extrusions'."
        )

    # ── Company-specific base path ─────────────────────────────────────────────
    _BASE_MAP = {
        "quant_gulf":      settings.QUANT_GULF_INVOICE_BASE_PATH,
        "gulf_extrusions": settings.GULF_INVOICE_BASE_PATH,
    }
    base = Path(_BASE_MAP[company_key])
    print(f"[INVOICE] company={company_key!r}  base={base}", flush=True)
    logger.info("Invoice base path: %s  (company=%s)", base, company_key)

    today = _date.today()
    year  = today.year
    month = today.month

    # ── Folder — always derived from today's date; created if absent ───────────
    folder = base / str(year) / str(month).zfill(2)
    created = not folder.exists()
    folder.mkdir(parents=True, exist_ok=True)
    print(f"[INVOICE] folder={folder}  created={created}", flush=True)
    logger.info("Invoice folder: %s  (new=%s)", folder, created)

    # ── Invoice number — manual override takes priority over auto-increment ───
    if forced_invoice_no is not None:
        invoice_no = forced_invoice_no
        print(f"[INVOICE] invoice_no={invoice_no} (manual override)", flush=True)
        logger.info("Invoice number: %d  (manual override)", invoice_no)
    else:
        invoice_no = _next_invoice_seq(base, layout["seq_keyword"], layout["seq_floor"])
        print(f"[INVOICE] invoice_no={invoice_no} (auto)", flush=True)
        logger.info("Invoice number: %d  (auto, company=%s)", invoice_no, company_key)

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
        company_key=company_key,
        client_name=client_name,
        date=date_str,
        invoice_no=invoice_no,
        lpo=lpo,
        do_no=do_no,
        attn=attn,
        trn=trn,
        items=inv_items,
        tax=tax,
        total=total,
    )

    # ── File paths — DATE DISPLAY_NAME SEQNO.xlsx ──────────────────────────────
    display_name = layout["display_name"]
    safe_date    = sanitize_date(date_str)
    stem         = f"{safe_date} {display_name} {invoice_no}"
    excel_path   = folder / f"{stem}.xlsx"

    # ── Write Excel ────────────────────────────────────────────────────────────
    fill_invoice_template(request, excel_path)
    print(f"[INVOICE] Excel saved: {excel_path}", flush=True)
    logger.info("Invoice Excel written: %s", excel_path)

    # ── Export PDF ─────────────────────────────────────────────────────────────
    pdf_result = export_to_pdf(excel_path)
    print(f"[INVOICE] PDF status={pdf_result['status']}  path={pdf_result['pdf_path']}", flush=True)
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
