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
from difflib import SequenceMatcher
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


def _fuzzy_score(query: str, stem: str) -> float:
    """
    Score how well `query` matches `stem` (both pre-normalized).
    Returns 0.0–1.0. Uses substring check + word overlap + sequence similarity.
    """
    if query in stem:
        return 1.0
    q_words = query.split()
    s_words = stem.split()
    word_hits = sum(1 for w in q_words if any(w in sw for sw in s_words))
    word_score = word_hits / max(len(q_words), 1)
    seq_score  = SequenceMatcher(None, query, stem).ratio()
    return max(word_score * 0.9, seq_score)


def search_docs(query: str) -> "tuple[list[Path], list[Path], bool]":
    """
    Search DOCS_FOLDER for files matching `query`.

    Returns (matches, all_files, is_fuzzy):
      matches   — matching Path objects (exact first, then fuzzy fallback)
      all_files — full list of files in the folder
      is_fuzzy  — True when result came from fuzzy/typo matching
    """
    folder = _resolve_folder()

    logger.info("DOCS_FOLDER path: %s  exists=%s", folder, folder.exists())

    if not folder.exists():
        logger.warning("Documents folder not found: %s", folder)
        return [], [], False

    all_files = [p for p in folder.iterdir() if p.is_file()]
    logger.info("Files in folder (%d): %s", len(all_files), [f.name for f in all_files])

    q = _normalize(query)
    logger.info("Normalized query: %r", q)

    # ── Exact substring match ─────────────────────────────────────────────────
    exact = [f for f in all_files if q in _normalize(f.stem)]
    if exact:
        logger.info("Exact matches: %s", [f.name for f in exact])
        return exact, all_files, False

    # ── Fuzzy fallback ────────────────────────────────────────────────────────
    scored = sorted(
        ((f, _fuzzy_score(q, _normalize(f.stem))) for f in all_files),
        key=lambda x: x[1],
        reverse=True,
    )
    threshold = 0.45
    fuzzy = [f for f, score in scored if score >= threshold]
    logger.info("Fuzzy matches (threshold=%.2f): %s", threshold, [f.name for f in fuzzy[:5]])
    return fuzzy[:3], all_files, bool(fuzzy)
