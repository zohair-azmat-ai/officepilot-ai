"""
services/file_naming.py — Build Windows-safe filenames in the office naming convention.

Naming format:
    DD-MM-YYYY ref# XXXX CLIENT NAME.xlsx
    DD-MM-YYYY ref# XXXX CLIENT NAME.pdf

Sanitisation steps applied to the client name:
  1. Strip ASCII control characters (0x00-0x1F, 0x7F) — can arrive from
     copy-paste or NL-parser output and cause WinError 123 silently.
  2. Remove the 9 characters that Windows forbids in file names:
         \\ / : * ? " < > |
  3. Remove known parser artefacts appended to client names:
         "Item N", "No N", "no. N", "Nos N", "Pcs N", "Units N",
         stray "of", "for", "to" at the end, etc.
  4. Collapse consecutive whitespace → single space.
  5. Strip leading/trailing whitespace and dots (Windows rejects trailing dots).
  6. Upper-case (matches your existing folder naming style).
  7. Ensure the name is never empty (fallback: "CLIENT").

Sanitisation applied to the date string:
  • Slashes are converted to hyphens so "17/04/2026" works as well as "17-04-2026".
  • Any remaining illegal characters are removed.

Filename length:
  • Client name is capped at 60 characters before assembly.
  • Total filename is capped at 200 characters (well within Windows' 255-byte
    per-component limit, leaving headroom for long folder paths).
"""

import re
from pathlib import Path


# ── Patterns ──────────────────────────────────────────────────────────────────

# Windows-illegal filename characters
_WIN_ILLEGAL = re.compile(r'[\\/:*?"<>|]')

# ASCII control characters (includes tab, newline, carriage-return, null, etc.)
_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')

# Parser artefacts that sometimes trail the client name:
#   "Item 1", "No 2", "no. 3", "2 Nos", "x2", "2pcs", etc.
_TRAILING_ARTEFACTS = re.compile(
    r"""
    # trailing quantifier phrases
    (?:\s+
        (?:
            item\s*\d+           |   # "Item 1", "item3"
            no\.?\s*\d+          |   # "No 2", "no.3"
            nos?\.?\s*\d*        |   # "nos", "no.", "nos 3"
            pcs?\.?\s*\d*        |   # "pcs", "pc 2"
            units?\s*\d*         |   # "unit", "units 2"
            pieces?\s*\d*        |   # "piece", "pieces"
            x\s*\d+              |   # "x2", "x 10"
            \d+\s*-?\s*nos?\.?   |   # "2 nos", "2nos."
            \d+\s*-?\s*pcs?\.?   |   # "3 pcs"
            \d+\s*-?\s*units?        # "4 units"
        )
    )+
    $
    """,
    re.I | re.X,
)

# Trailing prepositions/conjunctions left over after artefact removal
_TRAILING_WORDS = re.compile(
    r'\s+(?:of|for|to|and|the|a|an|with|by|in|at|from)\s*$',
    re.I,
)

# Collapse runs of whitespace
_MULTI_SPACE = re.compile(r'\s+')

# Windows reserved filenames (case-insensitive, with or without extension)
_WIN_RESERVED = re.compile(
    r'^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..+)?$',
    re.I,
)

# Max characters kept for the client portion of the filename
_CLIENT_MAX_LEN = 60

# Hard cap on the total assembled filename (before extension)
_STEM_MAX_LEN = 200


# ── Helpers ───────────────────────────────────────────────────────────────────

def sanitize_client_name(raw: str) -> str:
    """
    Convert an arbitrary client name string into a Windows-safe, upper-cased
    token suitable for embedding in a filename.

    Examples
    --------
    >>> sanitize_client_name("Gulf Extrusion")
    'GULF EXTRUSION'
    >>> sanitize_client_name('Global Food Industries Item 1')
    'GLOBAL FOOD INDUSTRIES'
    >>> sanitize_client_name('A/B: Test "Co." nos 3')
    'AB TEST CO'
    >>> sanitize_client_name('\\tABB\\nCompany')
    'ABB COMPANY'
    """
    text = str(raw)

    # 1. Strip control characters (tab, newline, null, etc.)
    text = _CONTROL_CHARS.sub(" ", text)

    # 2. Remove Windows-illegal characters
    text = _WIN_ILLEGAL.sub("", text)

    # 3. Remove trailing parser artefacts ("Item 1", "2 nos", etc.)
    text = _TRAILING_ARTEFACTS.sub("", text)

    # 4. Remove any trailing prepositions left behind
    text = _TRAILING_WORDS.sub("", text)

    # 5. Collapse whitespace
    text = _MULTI_SPACE.sub(" ", text).strip(". ")

    # 6. Upper-case
    text = text.upper()

    # 7. Enforce length cap
    if len(text) > _CLIENT_MAX_LEN:
        text = text[:_CLIENT_MAX_LEN].rsplit(" ", 1)[0]  # break on word boundary
    text = text.strip(". ")

    # 8. Fallback — never return an empty string
    if not text:
        text = "CLIENT"

    # 9. Guard against Windows reserved names (CON, NUL, COM1, …)
    if _WIN_RESERVED.match(text):
        text = f"_{text}"

    return text


def sanitize_date(raw: str) -> str:
    """
    Ensure the date string is safe for use in a filename.

    Accepts "DD-MM-YYYY" or "DD/MM/YYYY"; always returns "DD-MM-YYYY".
    Any remaining illegal Windows characters are stripped.

    >>> sanitize_date("17/04/2026")
    '17-04-2026'
    >>> sanitize_date("17-04-2026")
    '17-04-2026'
    """
    # Normalise slashes to hyphens
    text = raw.replace("/", "-").replace("\\", "-")
    # Strip any remaining illegal characters
    text = _WIN_ILLEGAL.sub("", text)
    # Strip control chars
    text = _CONTROL_CHARS.sub("", text)
    return text.strip()


def build_filename(date: str, ref_no: int, client_name: str, ext: str) -> str:
    """
    Produce the full filename (without directory path).

    Parameters
    ----------
    date        : str  — "DD-MM-YYYY" (or "DD/MM/YYYY"; normalised internally)
    ref_no      : int  — e.g. 2703
    client_name : str  — raw client name (sanitised here)
    ext         : str  — ".xlsx" or ".pdf" (dot is optional)

    Returns
    -------
    str — e.g.  "17-04-2026 ref# 2704 GLOBAL FOOD INDUSTRIES.xlsx"
    """
    safe_date   = sanitize_date(date)
    safe_client = sanitize_client_name(client_name)
    ext         = "." + ext.lstrip(".")   # ensure leading dot

    stem = f"{safe_date} ref# {ref_no} {safe_client}"

    # Cap total stem length (protects against absurdly long descriptions
    # bleeding into client name from the NL parser)
    if len(stem) > _STEM_MAX_LEN:
        # Trim the client portion so the fixed parts (date + ref#) are intact
        fixed = f"{safe_date} ref# {ref_no} "
        remaining = _STEM_MAX_LEN - len(fixed)
        safe_client = safe_client[:max(remaining, 10)].rsplit(" ", 1)[0].strip(". ")
        stem = f"{fixed}{safe_client}"

    return stem + ext


def build_output_paths(
    folder: Path,
    date: str,
    ref_no: int,
    client_name: str,
) -> tuple[Path, Path]:
    """
    Return (excel_path, pdf_path) inside `folder`.

    Both share the same base name; only the extension differs.
    """
    excel_name = build_filename(date, ref_no, client_name, ".xlsx")
    pdf_name   = build_filename(date, ref_no, client_name, ".pdf")
    return folder / excel_name, folder / pdf_name
