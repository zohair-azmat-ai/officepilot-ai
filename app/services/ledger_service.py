"""
services/ledger_service.py — Persistence and business logic for Customer Ledger.

Storage: two JSON files — invoices.json and payments.json — inside the same
data directory used by company_memory (respects OFFICEPILOT_DATA_DIR).

Ledger computation is done at query time (no de-normalised cache).
"""

import json
import os
import logging
from datetime import date, timedelta
from pathlib import Path

from app.schemas.ledger import (
    Invoice, InvoiceCreate,
    Payment, PaymentCreate,
    PaymentSummary, InvoiceLedgerLine,
    CompanyLedgerSummary, LedgerOverview,
)

logger = logging.getLogger(__name__)


# ── Data directory ─────────────────────────────────────────────────────────────

def _data_dir() -> Path:
    d = os.environ.get("OFFICEPILOT_DATA_DIR")
    return Path(d) if d else Path(__file__).parent.parent.parent / "data"


def _invoices_path() -> Path:
    return _data_dir() / "invoices.json"


def _payments_path() -> Path:
    return _data_dir() / "payments.json"


# ── JSON helpers ───────────────────────────────────────────────────────────────

def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Could not parse %s — returning empty list", path)
        return []


def _save(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


# ── Date helpers ───────────────────────────────────────────────────────────────

def _parse_dmy(s: str) -> date:
    d, m, y = s.split("-")
    return date(int(y), int(m), int(d))


def _fmt_dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# ── Invoice CRUD ───────────────────────────────────────────────────────────────

def create_invoice(req: InvoiceCreate) -> Invoice:
    from datetime import datetime

    if not req.due_date:
        inv_d = _parse_dmy(req.invoice_date)
        due_date = _fmt_dmy(inv_d + timedelta(days=req.payment_terms_days))
    else:
        due_date = req.due_date

    records = _load(_invoices_path())
    inv_id  = f"INV-{len(records) + 1:04d}"

    inv = Invoice(
        id                 = inv_id,
        company_name       = req.company_name,
        invoice_number     = req.invoice_number,
        invoice_date       = req.invoice_date,
        lpo_number         = req.lpo_number,
        amount             = req.amount,
        payment_terms_days = req.payment_terms_days,
        due_date           = due_date,
        remarks            = req.remarks,
        created_at         = datetime.now().isoformat(),
    )
    records.append(inv.model_dump())
    _save(_invoices_path(), records)
    logger.info("Invoice created: %s for %s", inv_id, req.company_name)
    return inv


def get_invoices(company: str | None = None) -> list[Invoice]:
    rows = _load(_invoices_path())
    invs = [Invoice(**r) for r in rows]
    if company:
        invs = [i for i in invs if i.company_name.upper() == company.upper()]
    return invs


def get_invoice_by_id(inv_id: str) -> Invoice | None:
    for r in _load(_invoices_path()):
        if r.get("id") == inv_id:
            return Invoice(**r)
    return None


def delete_invoice(inv_id: str) -> bool:
    records = _load(_invoices_path())
    target  = next((Invoice(**r) for r in records if r.get("id") == inv_id), None)
    if not target:
        return False
    records = [r for r in records if r.get("id") != inv_id]
    _save(_invoices_path(), records)
    # Remove associated payments
    pays = [p for p in _load(_payments_path())
            if p.get("invoice_number") != target.invoice_number
            or p.get("company_name", "").upper() != target.company_name.upper()]
    _save(_payments_path(), pays)
    return True


# ── Payment CRUD ───────────────────────────────────────────────────────────────

def create_payment(req: PaymentCreate) -> Payment:
    from datetime import datetime

    records = _load(_payments_path())
    pay_id  = f"PAY-{len(records) + 1:04d}"

    pay = Payment(
        id              = pay_id,
        company_name    = req.company_name,
        invoice_number  = req.invoice_number,
        payment_date    = req.payment_date,
        amount_received = req.amount_received,
        payment_mode    = req.payment_mode,
        remarks         = req.remarks,
        created_at      = datetime.now().isoformat(),
    )
    records.append(pay.model_dump())
    _save(_payments_path(), records)
    logger.info("Payment recorded: %s for invoice %s", pay_id, req.invoice_number)
    return pay


def get_payments(invoice_number: str | None = None) -> list[Payment]:
    rows = _load(_payments_path())
    pays = [Payment(**r) for r in rows]
    if invoice_number:
        pays = [p for p in pays if p.invoice_number == invoice_number]
    return pays


def delete_payment(pay_id: str) -> bool:
    records = _load(_payments_path())
    new     = [r for r in records if r.get("id") != pay_id]
    if len(new) == len(records):
        return False
    _save(_payments_path(), new)
    return True


# ── Ledger computation ─────────────────────────────────────────────────────────

def _ledger_line(inv: Invoice, pay_rows: list[dict]) -> InvoiceLedgerLine:
    received = round(sum(p.get("amount_received", 0) for p in pay_rows), 2)
    balance  = round(inv.amount - received, 2)

    if balance <= 0.005:
        status  = "PAID"
        balance = 0.0
    elif received > 0:
        status = "PARTIALLY PAID"
    else:
        status = "UNPAID"

    overdue = False
    if inv.due_date and balance > 0:
        try:
            overdue = _parse_dmy(inv.due_date) < date.today()
        except Exception:
            pass

    return InvoiceLedgerLine(
        invoice_id     = inv.id,
        company_name   = inv.company_name,
        invoice_number = inv.invoice_number,
        lpo_number     = inv.lpo_number or "",
        invoice_date   = inv.invoice_date,
        due_date       = inv.due_date or "",
        amount         = inv.amount,
        received       = received,
        balance        = balance,
        status         = status,
        overdue        = overdue,
        remarks        = inv.remarks or "",
        payments       = [
            PaymentSummary(
                id              = p.get("id", ""),
                payment_date    = p.get("payment_date", ""),
                amount_received = p.get("amount_received", 0),
                payment_mode    = p.get("payment_mode", ""),
                remarks         = p.get("remarks", ""),
            )
            for p in pay_rows
        ],
    )


def get_ledger_overview() -> LedgerOverview:
    invoices     = [Invoice(**r) for r in _load(_invoices_path())]
    all_payments = _load(_payments_path())

    # Index payments by invoice_number
    pay_idx: dict[str, list[dict]] = {}
    for p in all_payments:
        pay_idx.setdefault(p.get("invoice_number", ""), []).append(p)

    # Group invoices by company
    by_company: dict[str, list[Invoice]] = {}
    for inv in invoices:
        by_company.setdefault(inv.company_name, []).append(inv)

    summaries: list[CompanyLedgerSummary] = []
    grand_inv = grand_rec = 0.0

    for cname in sorted(by_company):
        lines = [
            _ledger_line(inv, pay_idx.get(inv.invoice_number, []))
            for inv in sorted(by_company[cname],
                              key=lambda x: x.invoice_date, reverse=True)
        ]
        ti = round(sum(l.amount   for l in lines), 2)
        tr = round(sum(l.received for l in lines), 2)
        grand_inv += ti
        grand_rec += tr

        summaries.append(CompanyLedgerSummary(
            company_name   = cname,
            total_invoiced = ti,
            total_received = tr,
            outstanding    = round(ti - tr, 2),
            invoice_count  = len(lines),
            overdue_count  = sum(1 for l in lines if l.overdue),
            invoices       = lines,
        ))

    return LedgerOverview(
        total_invoiced = round(grand_inv, 2),
        total_received = round(grand_rec, 2),
        outstanding    = round(grand_inv - grand_rec, 2),
        companies      = summaries,
    )


def get_company_ledger(company_name: str) -> CompanyLedgerSummary | None:
    for cs in get_ledger_overview().companies:
        if cs.company_name.upper() == company_name.upper():
            return cs
    return None
