"""
services/ref_parser.py — Scan a folder and determine the next quotation ref number.

Handles messy real-world filename variations:
  - "ref# 2702"
  - "ref # 2702"
  - "Ref#2702"
  - "REF # 2702"
  - any amount of whitespace between "ref", "#" and the digits
"""

import re
from pathlib import Path


# Regex that matches every known variant of the ref number pattern.
# Captures the numeric part only.
_REF_PATTERN = re.compile(
    r"ref\s*#\s*(\d+)",
    re.IGNORECASE,
)


def extract_ref_number(filename: str) -> int | None:
    """
    Parse a single filename and return the ref number as an integer.
    Returns None if no ref number is found.

    Examples
    --------
    >>> extract_ref_number("16-04-2026 ref# 2702 GULF EXTRUSION.xlsx")
    2702
    >>> extract_ref_number("04-04-2026 Ref#2691 Gulf.pdf")
    2691
    >>> extract_ref_number("some random file.xlsx")
    None
    """
    match = _REF_PATTERN.search(filename)
    if match:
        return int(match.group(1))
    return None


def scan_folder_for_max_ref(folder: Path) -> int | None:
    """
    Walk *only the top level* of `folder` and find the highest ref number
    across all .xlsx and .pdf files.

    Returns
    -------
    int  — highest ref number found, or
    None — if the folder is empty / no matching files exist yet.
    """
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {folder}")

    max_ref: int | None = None

    # Scan only the immediate children (not recursive) — month folders are flat
    for entry in folder.iterdir():
        if entry.is_file() and entry.suffix.lower() in {".xlsx", ".pdf", ".xls"}:
            ref = extract_ref_number(entry.name)
            if ref is not None:
                if max_ref is None or ref > max_ref:
                    max_ref = ref

    return max_ref


def get_next_ref_number(folder: Path, start: int = 1) -> int:
    """
    Return the next sequential ref number for `folder`.

    If the folder has no existing quotations yet, returns `start` (default 1).
    Otherwise returns max_ref + 1.

    Parameters
    ----------
    folder : Path — the month folder to scan
    start  : int  — fallback starting ref if folder is empty
    """
    max_ref = scan_folder_for_max_ref(folder)
    if max_ref is None:
        return start
    return max_ref + 1
