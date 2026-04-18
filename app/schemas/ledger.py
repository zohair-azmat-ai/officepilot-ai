"""
schemas/ledger.py — Pydantic models for the Customer Ledger / AR module.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, field_validator


# ── Invoice ───────────────────────────────────────────────────────────────────

class InvoiceCreate(BaseModel):
    company_name:       str
    invoice_number:     str   = Field(..., min_length=1)
    invoice_date:       str                           # DD-MM-YYYY
    lpo_number:         str   = ""
    amount:             float = Field(..., gt=0)
    payment_terms_days: int   = Field(30, ge=0)
    due_date:           str   = ""                    # auto-computed if blank
    remarks:            str   = ""

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        if not v:
            return v
        parts = v.split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError("date must be DD-MM-YYYY, e.g. '18-04-2026'")
        return v


class Invoice(InvoiceCreate):
    id:         str
    created_at: str


# ── Payment ───────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    company_name:    str
    invoice_number:  str   = Field(..., min_length=1)
    payment_date:    str                              # DD-MM-YYYY
    amount_received: float = Field(..., gt=0)
    payment_mode:    str   = "Bank Transfer"
    remarks:         str   = ""

    @field_validator("payment_date", mode="before")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        if not v:
            return v
        parts = v.split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError("date must be DD-MM-YYYY")
        return v


class Payment(PaymentCreate):
    id:         str
    created_at: str


# ── Ledger view ───────────────────────────────────────────────────────────────

class PaymentSummary(BaseModel):
    id:              str
    payment_date:    str
    amount_received: float
    payment_mode:    str
    remarks:         str


class InvoiceLedgerLine(BaseModel):
    invoice_id:     str
    company_name:   str
    invoice_number: str
    lpo_number:     str
    invoice_date:   str
    due_date:       str
    amount:         float
    received:       float
    balance:        float
    status:         Literal["UNPAID", "PARTIALLY PAID", "PAID"]
    overdue:        bool
    remarks:        str
    payments:       list[PaymentSummary] = []


class CompanyLedgerSummary(BaseModel):
    company_name:    str
    total_invoiced:  float
    total_received:  float
    outstanding:     float
    invoice_count:   int
    overdue_count:   int
    invoices:        list[InvoiceLedgerLine]


class LedgerOverview(BaseModel):
    total_invoiced: float
    total_received: float
    outstanding:    float
    companies:      list[CompanyLedgerSummary]
