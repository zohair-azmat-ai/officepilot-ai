"""
schemas/company.py — Pydantic models for the company memory store.
"""

from pydantic import BaseModel


class CompanyRecord(BaseModel):
    company_name:       str
    aliases:            list[str] = []
    attn:               str = ""
    trn:                str = ""
    phone:              str = ""
    fax:                str = ""
    payment_terms_days: int = 30
