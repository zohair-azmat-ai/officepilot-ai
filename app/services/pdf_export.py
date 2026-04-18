"""
services/pdf_export.py — Export an Excel file to PDF via LibreOffice headless.

Strategy
--------
1. Look for a LibreOffice executable at each path listed in config.LIBREOFFICE_PATHS.
2. If found, run:
       soffice.exe --headless --convert-to pdf --outdir <folder> <excel_file>
3. LibreOffice places the PDF next to the Excel file with the same base name.
4. If LibreOffice is not installed (or the conversion fails for any reason),
   return a structured result instead of raising — the caller decides what to
   surface to the user.

The function never crashes the parent workflow; it always returns a dict
describing what happened.
"""

import subprocess
import logging
from pathlib import Path
from typing import TypedDict, Literal

from app.config import settings

logger = logging.getLogger(__name__)


class PdfResult(TypedDict):
    status:  Literal["created", "skipped", "failed"]
    message: str
    pdf_path: str | None


def _find_libreoffice() -> Path | None:
    """Return the first LibreOffice executable that exists, or None."""
    for path_str in settings.LIBREOFFICE_PATHS:
        p = Path(path_str)
        if p.exists():
            return p
    return None


def export_to_pdf(excel_path: Path) -> PdfResult:
    """
    Convert `excel_path` to PDF using LibreOffice headless.

    The PDF is written to the same directory as the Excel file.
    Returns a PdfResult dict that always has status / message / pdf_path keys.

    Parameters
    ----------
    excel_path : Path — absolute path to the .xlsx file to convert

    Returns
    -------
    PdfResult — status is one of:
        "created"  — PDF was successfully created
        "skipped"  — LibreOffice not found; PDF export is not possible locally
        "failed"   — LibreOffice found but conversion raised an error
    """
    if not excel_path.exists():
        return PdfResult(
            status="failed",
            message=f"Excel file not found, cannot convert: {excel_path}",
            pdf_path=None,
        )

    libreoffice = _find_libreoffice()

    # ── LibreOffice not installed ──────────────────────────────────────────────
    if libreoffice is None:
        msg = (
            "LibreOffice not found on this machine. "
            "PDF export skipped. "
            "Install LibreOffice from https://www.libreoffice.org/download/ "
            "and ensure it is in one of the configured paths."
        )
        logger.warning(msg)
        return PdfResult(status="skipped", message=msg, pdf_path=None)

    # ── Run LibreOffice conversion ─────────────────────────────────────────────
    output_dir = excel_path.parent
    expected_pdf = output_dir / (excel_path.stem + ".pdf")

    cmd = [
        str(libreoffice),
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(excel_path),
    ]

    logger.info("Running LibreOffice: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,   # 60-second safety timeout
        )

        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            logger.error("LibreOffice exited with code %d: %s", result.returncode, err)
            return PdfResult(
                status="failed",
                message=f"LibreOffice conversion failed (exit {result.returncode}): {err}",
                pdf_path=None,
            )

        # LibreOffice names the output after the input stem
        if expected_pdf.exists():
            logger.info("PDF created: %s", expected_pdf)
            return PdfResult(
                status="created",
                message="PDF exported successfully via LibreOffice.",
                pdf_path=str(expected_pdf),
            )
        else:
            # Conversion claimed success but file is missing — edge case
            return PdfResult(
                status="failed",
                message=(
                    "LibreOffice reported success but PDF file not found at "
                    f"{expected_pdf}. Check LibreOffice permissions / temp space."
                ),
                pdf_path=None,
            )

    except subprocess.TimeoutExpired:
        return PdfResult(
            status="failed",
            message="LibreOffice conversion timed out after 60 seconds.",
            pdf_path=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during PDF export")
        return PdfResult(
            status="failed",
            message=f"Unexpected error: {exc}",
            pdf_path=None,
        )
