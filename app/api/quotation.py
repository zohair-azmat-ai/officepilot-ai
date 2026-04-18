"""
api/quotation.py — FastAPI router for the Quotation module.

Endpoints
─────────
  POST /quotations/create         — create quotation from structured form data
  POST /quotations/parse-command  — parse natural-language command into fields
  GET  /quotations/health         — liveness check
"""

import logging
from fastapi import APIRouter, HTTPException, status

from app.schemas.quotation import (
    QuotationCreateRequest,
    QuotationCreateResponse,
    ErrorResponse,
)
from app.schemas.command import (
    ParseCommandRequest,
    ParseCommandResponse,
)
from app.services.quotation_service import create_quotation
from app.services.command_parser    import parse_quotation_command

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quotations", tags=["Quotations"])


# ── Create ─────────────────────────────────────────────────────────────────────

@router.post(
    "/create",
    response_model=QuotationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new quotation",
    responses={
        400: {"model": ErrorResponse, "description": "Bad request / validation error"},
        404: {"model": ErrorResponse, "description": "Template or folder not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
def create_quotation_endpoint(request: QuotationCreateRequest) -> QuotationCreateResponse:
    """
    Create a new quotation Excel file (and optionally PDF) in the configured
    Quotation folder for the given year and month.
    """
    try:
        return create_quotation(request)
    except FileNotFoundError as exc:
        logger.warning("FileNotFoundError: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        logger.warning("NotADirectoryError: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("ValueError: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while creating quotation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {exc}",
        ) from exc


# ── Parse command ──────────────────────────────────────────────────────────────

@router.post(
    "/parse-command",
    response_model=ParseCommandResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse a natural-language command into quotation fields",
    responses={
        400: {"model": ErrorResponse, "description": "Empty command"},
        500: {"model": ErrorResponse, "description": "Parse error"},
    },
)
def parse_command_endpoint(request: ParseCommandRequest) -> ParseCommandResponse:
    """
    Parse a plain-English quotation command and return structured fields.

    The response includes:
    - `parsed`     — all extracted field values (same shape as /create payload)
    - `confidence` — per-field bool: True = explicitly found, False = defaulted
    - `warnings`   — human-readable notes about defaults or missing fields

    The frontend can display the parsed preview, let the user confirm, then
    forward `parsed` directly to POST /quotations/create.
    """
    if not request.command or not request.command.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Command text is empty.",
        )
    try:
        return parse_quotation_command(request.command)
    except Exception as exc:
        logger.exception("Unexpected error while parsing command")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Parse error: {exc}",
        ) from exc


# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health", summary="Health check", tags=["Health"])
def health_check() -> dict:
    """Simple liveness check — returns 200 if the server is running."""
    return {"status": "ok", "module": "quotations"}
