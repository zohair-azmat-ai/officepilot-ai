"""
api/ledger.py — REST endpoints for Customer Ledger / Accounts Receivable.

Endpoints
─────────
  POST   /ledger/invoices              — create invoice
  GET    /ledger/invoices              — list invoices (optional ?company=)
  DELETE /ledger/invoices/{id}         — delete invoice + its payments

  POST   /ledger/payments              — record payment
  GET    /ledger/payments              — list payments (optional ?invoice_number=)
  DELETE /ledger/payments/{id}         — delete single payment

  GET    /ledger/overview              — full ledger overview (all companies)
  GET    /ledger/company/{name}        — single-company ledger
"""

import logging
from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.ledger import (
    InvoiceCreate, Invoice,
    PaymentCreate, Payment,
    CompanyLedgerSummary, LedgerOverview,
)
from app.services.ledger_service import (
    create_invoice, get_invoices, get_invoice_by_id, delete_invoice,
    create_payment, get_payments, delete_payment,
    get_ledger_overview, get_company_ledger,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ledger", tags=["Ledger"])


# ── Invoices ──────────────────────────────────────────────────────────────────

@router.post("/invoices", response_model=Invoice, status_code=status.HTTP_201_CREATED)
def add_invoice(req: InvoiceCreate):
    try:
        return create_invoice(req)
    except Exception as exc:
        logger.exception("Error creating invoice")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/invoices", response_model=list[Invoice])
def list_invoices(company: str | None = Query(None)):
    return get_invoices(company=company)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_invoice(invoice_id: str):
    if not delete_invoice(invoice_id):
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id!r} not found")


# ── Payments ──────────────────────────────────────────────────────────────────

@router.post("/payments", response_model=Payment, status_code=status.HTTP_201_CREATED)
def add_payment(req: PaymentCreate):
    # Validate referenced invoice exists
    all_invs = get_invoices()
    inv_numbers = {i.invoice_number for i in all_invs}
    if req.invoice_number not in inv_numbers:
        raise HTTPException(
            status_code=404,
            detail=f"Invoice {req.invoice_number!r} not found. Create the invoice first.",
        )
    try:
        return create_payment(req)
    except Exception as exc:
        logger.exception("Error recording payment")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/payments", response_model=list[Payment])
def list_payments(invoice_number: str | None = Query(None)):
    return get_payments(invoice_number=invoice_number)


@router.delete("/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_payment(payment_id: str):
    if not delete_payment(payment_id):
        raise HTTPException(status_code=404, detail=f"Payment {payment_id!r} not found")


# ── Ledger views ──────────────────────────────────────────────────────────────

@router.get("/overview", response_model=LedgerOverview)
def ledger_overview():
    return get_ledger_overview()


@router.get("/company/{company_name}", response_model=CompanyLedgerSummary)
def company_ledger(company_name: str):
    cs = get_company_ledger(company_name)
    if not cs:
        raise HTTPException(
            status_code=404,
            detail=f"No ledger data for company: {company_name}",
        )
    return cs
