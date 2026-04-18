"""
services/quotation_service.py — High-level orchestrator for quotation creation.

This is the only place that combines all sub-services:
  1. Resolve the target folder from config + year + month
  2. Scan for the next ref number
  3. Build the output file paths
  4. Write the Excel file
  5. Export PDF (graceful failure)
  6. Return a structured response

The API route calls this function and returns its result directly.
"""

import logging
from pathlib import Path

from app.config import settings
from app.schemas.quotation import QuotationCreateRequest, QuotationCreateResponse
from app.services.ref_parser   import get_next_ref_number
from app.services.file_naming  import build_output_paths
from app.services.excel_writer import fill_template
from app.services.pdf_export   import export_to_pdf

logger = logging.getLogger(__name__)


def create_quotation(request: QuotationCreateRequest) -> QuotationCreateResponse:
    """
    End-to-end quotation creation.

    Parameters
    ----------
    request : QuotationCreateRequest — validated user payload from the API

    Returns
    -------
    QuotationCreateResponse — always returned (never raises to the route layer);
        exceptions are re-raised so the route layer can wrap them in HTTP errors.
    """

    # ── 1. Resolve folder path ─────────────────────────────────────────────────
    base = Path(settings.QUOTATION_BASE_PATH)
    folder = base / request.year / request.month

    logger.info("Target folder: %s", folder)

    # Create the folder if it doesn't exist yet (new month)
    folder.mkdir(parents=True, exist_ok=True)

    # ── 2. Detect next ref number ──────────────────────────────────────────────
    next_ref = get_next_ref_number(folder)
    logger.info("Next ref number: %d", next_ref)

    # ── 3. Build output paths ──────────────────────────────────────────────────
    excel_path, pdf_path = build_output_paths(
        folder=folder,
        date=request.date,
        ref_no=next_ref,
        client_name=request.client_name,
    )

    logger.info("Excel output: %s", excel_path)
    logger.info("PDF output:   %s", pdf_path)

    # ── 4. Write Excel ─────────────────────────────────────────────────────────
    fill_template(
        request=request,
        ref_no=next_ref,
        output_path=excel_path,
    )
    logger.info("Excel file written successfully.")

    # ── 5. Export PDF (non-fatal) ──────────────────────────────────────────────
    pdf_result = export_to_pdf(excel_path)
    logger.info("PDF result: %s — %s", pdf_result["status"], pdf_result["message"])

    # ── 6. Build response ──────────────────────────────────────────────────────
    return QuotationCreateResponse(
        success=True,
        new_ref_number=next_ref,
        excel_path=str(excel_path),
        pdf_path=pdf_result["pdf_path"],
        pdf_status=pdf_result["status"],
        pdf_message=pdf_result["message"],
        source_folder=str(folder),
        filename=excel_path.name,
    )
