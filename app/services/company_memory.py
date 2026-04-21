"""
services/company_memory.py — Persistent company record store.

Records live in data/companies.json (project root / data/).
Lookup is fuzzy: normalised uppercase, word-overlap scoring.
Writes are atomic: full list is serialised back on every upsert.
"""

import json
import os
import re
import shutil
import logging
from pathlib import Path

from app.schemas.company import CompanyRecord

logger = logging.getLogger(__name__)


def _resolve_data_path() -> Path:
    """
    Return the path to companies.json.

    In packaged (Electron) mode, OFFICEPILOT_DATA_DIR is set to
    app.getPath('userData') — a writable per-user directory.
    On first run we seed it from the bundled read-only copy so that
    the pre-loaded companies are available out of the box.

    In dev mode, use the project-local data/ folder.
    """
    data_dir = os.environ.get('OFFICEPILOT_DATA_DIR')
    if data_dir:
        dest = Path(data_dir) / 'companies.json'
        if not dest.exists():
            # Seed from bundled data (resourcesPath/backend/data/companies.json)
            resource_dir = os.environ.get('OFFICEPILOT_RESOURCE_DIR')
            if resource_dir:
                seed = Path(resource_dir) / 'data' / 'companies.json'
                if seed.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(seed, dest)
                    logger.info('Seeded companies.json from bundle to %s', dest)
        return dest

    # Development: data/ next to the project root
    return Path(__file__).parent.parent.parent / 'data' / 'companies.json'


_DATA_PATH = _resolve_data_path()


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Uppercase, collapse whitespace, strip punctuation noise."""
    s = re.sub(r"[^\w\s]", " ", name.upper())
    return re.sub(r"\s+", " ", s).strip()


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        with _DATA_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("companies.json could not be parsed; returning empty list")
        return []


def _save_all(records: list[dict]) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


# ── Public API ────────────────────────────────────────────────────────────────

def get_all() -> list[CompanyRecord]:
    """Return every stored company record."""
    return [CompanyRecord(**r) for r in _load()]


def _score(norm_q: str, q_words: set, candidate: str) -> int:
    """Score a normalised query against a single normalised candidate string."""
    norm_c = _normalize(candidate)
    c_words = set(norm_c.split())
    if norm_q == norm_c:
        return 100
    if norm_q in norm_c or norm_c in norm_q:
        return 80
    combined = q_words | c_words
    return int(100 * len(q_words & c_words) / len(combined)) if combined else 0


def lookup(query: str, max_results: int = 6) -> list[CompanyRecord]:
    """
    Return up to max_results records that best match the query string.

    Scoring (0–100):
      100  exact normalised match against company_name or any alias
       80  one string contains the other
       30+ word-overlap score

    Aliases are checked alongside the canonical name; the highest score wins.
    Only results with score >= 25 are returned.
    """
    if not query or not query.strip():
        return []

    norm_q = _normalize(query)
    q_words = set(norm_q.split())

    scored: list[tuple[int, CompanyRecord]] = []
    for raw in _load():
        rec = CompanyRecord(**raw)
        best = _score(norm_q, q_words, rec.company_name)
        for alias in rec.aliases:
            best = max(best, _score(norm_q, q_words, alias))
        if best >= 25:
            scored.append((best, rec))

    scored.sort(key=lambda x: -x[0])
    return [rec for _, rec in scored[:max_results]]


def resolve_company_name(query: str) -> str:
    """Return the canonical company_name for query (alias or partial name).
    Falls back to the query itself if no confident match is found."""
    if not query or not query.strip():
        return query
    norm_q = _normalize(query)
    # Exact alias match first (highest confidence)
    for raw in _load():
        rec = CompanyRecord(**raw)
        for alias in rec.aliases:
            if _normalize(alias) == norm_q:
                return rec.company_name
    # Fuzzy fallback
    matches = lookup(query, max_results=1)
    if matches:
        return matches[0].company_name
    return query


def get_exact(company_name: str) -> CompanyRecord | None:
    """Return a record whose normalised name exactly matches company_name."""
    norm = _normalize(company_name)
    for raw in _load():
        if _normalize(raw.get("company_name", "")) == norm:
            return CompanyRecord(**raw)
    return None


def upsert(record: CompanyRecord) -> None:
    """Insert or update a company record (matched by normalised name)."""
    records = _load()
    norm_new = _normalize(record.company_name)

    for i, r in enumerate(records):
        if _normalize(r.get("company_name", "")) == norm_new:
            records[i] = record.model_dump()
            _save_all(records)
            logger.info("Updated company: %s", record.company_name)
            return

    records.append(record.model_dump())
    _save_all(records)
    logger.info("Saved new company: %s", record.company_name)
