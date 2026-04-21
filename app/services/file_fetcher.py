"""
services/file_fetcher.py — Fetch documents from the fixed official-documents folder.

Only files inside DOCS_FOLDER are ever accessible (no path traversal).

Matching rules:
  - Case-insensitive
  - Extension stripped before matching
  - Spaces, underscores, and hyphens all treated as equivalent (normalized to space)
  - Partial match: query must appear anywhere in the normalized stem
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DOCS_FOLDER = Path(r"G:\NEW DATA 2021\DRIVE\Visa,Documents,etc\Offical Documents 2026")

# Alternative path with dot separator (in case Windows shows it differently)
_DOCS_FOLDER_ALT = Path(r"G:\NEW DATA 2021\DRIVE\Visa.Documents.etc\Offical Documents 2026")


def _resolve_folder() -> Path:
    """Return whichever docs folder path actually exists on disk."""
    if DOCS_FOLDER.exists():
        return DOCS_FOLDER
    if _DOCS_FOLDER_ALT.exists():
        return _DOCS_FOLDER_ALT
    return DOCS_FOLDER   # return primary even if missing — debug logging will catch it


def _normalize(s: str) -> str:
    """Lowercase and collapse spaces/underscores/hyphens to a single space."""
    return re.sub(r"[\s_\-]+", " ", s).strip().lower()


def search_docs(query: str) -> "tuple[list[Path], list[Path]]":
    """
    Search DOCS_FOLDER for files matching `query`.

    Matching: normalized query must appear anywhere in the normalized filename stem
    (extension is ignored during matching).

    Returns (matches, all_files):
      matches   — list of Path objects that match the query
      all_files — full list of files in the folder (for "no match" fallback message)
    """
    folder = _resolve_folder()

    logger.info("DOCS_FOLDER path: %s", folder)
    logger.info("DOCS_FOLDER exists: %s", folder.exists())

    if not folder.exists():
        logger.warning("Documents folder not found: %s", folder)
        return [], []

    all_files = [p for p in folder.iterdir() if p.is_file()]
    logger.info("Files found in folder (%d): %s", len(all_files), [f.name for f in all_files])

    q = _normalize(query)
    logger.info("Normalized query: %r", q)

    matches = [f for f in all_files if q in _normalize(f.stem)]
    logger.info("Matched files: %s", [f.name for f in matches])

    return matches, all_files
