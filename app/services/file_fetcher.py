"""
services/file_fetcher.py — Fetch documents from the fixed official-documents folder.

Only files inside DOCS_FOLDER are ever accessible (no path traversal).
"""

from pathlib import Path

DOCS_FOLDER = Path(r"G:\NEW DATA 2021\DRIVE\Visa,Documents,etc\Offical Documents 2026")


def search_docs(query: str) -> list[Path]:
    """
    Return files in DOCS_FOLDER whose names contain `query` (case-insensitive).
    Returns an empty list if the folder does not exist or nothing matches.
    """
    if not DOCS_FOLDER.exists():
        return []

    q = query.strip().lower()
    return [
        p for p in DOCS_FOLDER.iterdir()
        if p.is_file() and q in p.name.lower()
    ]
