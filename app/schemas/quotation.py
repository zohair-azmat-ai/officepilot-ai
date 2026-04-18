"""
schemas/quotation.py — Pydantic request / response models for the Quotation module.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Literal


# ── Line item ──────────────────────────────────────────────────────────────────

class QuotationItem(BaseModel):
    """A single line item in a quotation (used for multi-item requests)."""
    description: str
    size:        str   = ""
    quantity:    float
    rate:        float
    amount:      float = 0.0   # pre-computed by parser; recomputed in excel_writer


# ── Request ────────────────────────────────────────────────────────────────────

class QuotationCreateRequest(BaseModel):
    """
    Payload sent by the client to create a new quotation.

    Two modes:
      • Single-item (form): items=[] and the legacy description/quantity/rate
        fields are used.
      • Multi-item (Quick Command): items is non-empty and takes priority.
        The legacy fields are populated with the first item for backward compat.
    """

    year:        str   = Field(..., examples=["2026"])
    month:       str   = Field(..., examples=["04"])
    date:        str   = Field(..., examples=["16-04-2026"])
    client_name: str   = Field(..., examples=["Gulf Extrusion"])

    # ── Multi-item list (parser populates; empty for form submissions) ─────────
    items: list[QuotationItem] = []

    # ── Company detail fields (auto-filled from company memory) ──────────────
    attn:  str = Field("", examples=["MR. JOHN"])
    trn:   str = Field("", examples=["100211945900003"])
    phone: str = Field("", examples=["04-1234567"])
    fax:   str = Field("", examples=["04-1234567"])

    # ── Legacy single-item fields (backward compat with the HTML form) ─────────
    description: str   = Field("",  examples=["Fabrication of S.S Roller"])
    size:        str   = Field("",  examples=["40 x 120 mm long"])
    quantity:    float = Field(1.0, ge=0, examples=[1])
    rate:        float = Field(0.0, ge=0, examples=[500])
    tax:         float = Field(0.0, ge=0, examples=[25])
    total:       float = Field(0.0, ge=0, examples=[525])

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 4:
            raise ValueError("year must be a 4-digit string, e.g. '2026'")
        return v

    @field_validator("month")
    @classmethod
    def validate_month(cls, v: str) -> str:
        if not v.isdigit() or not (1 <= int(v) <= 12):
            raise ValueError("month must be 01-12")
        return v.zfill(2)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        parts = v.split("-")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError("date must be DD-MM-YYYY, e.g. '16-04-2026'")
        return v


# ── Response ───────────────────────────────────────────────────────────────────

class QuotationCreateResponse(BaseModel):
    success:         bool
    new_ref_number:  int
    excel_path:      str
    pdf_path:        str | None
    pdf_status:      Literal["created", "skipped", "failed"]
    pdf_message:     str
    source_folder:   str
    filename:        str


# ── Error ──────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    success: bool = False
    detail:  str
