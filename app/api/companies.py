"""
api/companies.py — REST endpoints for the company memory store.

Endpoints
─────────
  GET  /companies           — list all stored companies
  GET  /companies/lookup?q= — fuzzy search by name (returns up to 6 matches)
  POST /companies           — upsert a company record
"""

import logging
from fastapi import APIRouter, Query, status

from app.schemas.company import CompanyRecord
from app.services.company_memory import get_all, lookup, upsert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get("", response_model=list[CompanyRecord])
def list_companies():
    """Return all stored company records."""
    return get_all()


@router.get("/lookup", response_model=list[CompanyRecord])
def lookup_companies(q: str = Query(..., min_length=1, description="Company name search query")):
    """Fuzzy-search companies by name. Returns up to 6 best matches."""
    return lookup(q)


@router.post("", status_code=status.HTTP_201_CREATED)
def save_company(record: CompanyRecord):
    """Insert or update a company record (matched by normalised name)."""
    upsert(record)
    return {"saved": True, "company_name": record.company_name}
