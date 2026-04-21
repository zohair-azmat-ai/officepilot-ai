"""
services/excel_writer.py — Fill the company quotation template with new data.

Why zipfile + ElementTree instead of openpyxl?
───────────────────────────────────────────────
openpyxl does NOT fully round-trip embedded images (logos, stamps, drawings).
When you open a workbook and save it via openpyxl, the binary drawing
relationships are silently dropped, so the output file is missing the
letterhead artwork (hdphoto1.wdp, image1.jpeg, image2.png).

The fix: treat the .xlsx as the ZIP archive it actually is.
  1. shutil.copy2 clones the template byte-for-byte.
  2. All zip entries are read into memory as raw bytes.
  3. ONLY xl/worksheets/sheet1.xml is parsed and modified via ElementTree.
  4. All other entries (media, drawings, styles, strings…) are written back
     unchanged — the images literally never leave memory as raw bytes.

Template layout (rows)
──────────────────────
  A1:M11  — Company header / logo / stamp  ← NEVER TOUCH
  Row 12  B12        ← Client name    (merged B12:G12)
  Row 14  K14        ← Ref no         (merged K14:L14)
  Row 16  K16        ← Date           (merged K16:L16)
  Row 18  — Table header row           ← NEVER TOUCH
  Row 19  — Sub-header row             ← NEVER TOUCH
  Row 20  — Item 1 main row (H20:I20 merged for Qty, J20:K20 merged for Rate)
  Row 21  — Sub-description row (B21:G21 merged) — used for description overflow.
  Rows 22–35 — Item rows 2–15 (H:I merged, J:K merged, 20.25pt height each)

  Row 36  L36  ← Subtotal
  Row 37  L37  ← VAT / tax
  Row 38  L38  ← Total amount
  Row 40  C40  ← Amount in words (merged C40:K40)
  Row 40  L40  ← Total amount (bottom copy, merged L40:L41)
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from app.config import settings
from app.schemas.quotation import QuotationCreateRequest

# ── xlsx / SpreadsheetML namespace ────────────────────────────────────────────

_NS_MAIN  = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R     = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_MC    = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_NS_X14AC = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"

_SHEET_ENTRY = "xl/worksheets/sheet1.xml"

# ── Item-area constants ───────────────────────────────────────────────────────

ITEM_ROW_START = 20
ITEM_ROW_MAX   = 35

# Row 21 is a sub-description row where the H column is only 1.28pt wide.
# Writing qty there makes it invisible — skip it for multi-item mode.
# Each entry in this list is a fully-formatted item row (correct merges/borders).
_MULTI_ITEM_ROWS = [20] + list(range(22, 36))   # 15 items max

# Approximate row height per line of wrapped text (points, ~11pt font)
_ROW_HEIGHT_PER_LINE = 20.25


# ── Amount-in-words ───────────────────────────────────────────────────────────

_ONES = [
    '', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
    'TEN', 'ELEVEN', 'TWELVE', 'THIRTEEN', 'FOURTEEN', 'FIFTEEN', 'SIXTEEN',
    'SEVENTEEN', 'EIGHTEEN', 'NINETEEN',
]
_TENS = ['', '', 'TWENTY', 'THIRTY', 'FORTY', 'FIFTY',
         'SIXTY', 'SEVENTY', 'EIGHTY', 'NINETY']


def _int_to_words(n: int) -> str:
    """Convert a non-negative integer to English words (uppercase)."""
    if n == 0:
        return ''
    parts = []
    if n >= 1_000_000:
        parts.append(f'{_int_to_words(n // 1_000_000)} MILLION')
        n %= 1_000_000
    if n >= 1_000:
        parts.append(f'{_int_to_words(n // 1_000)} THOUSAND')
        n %= 1_000
    if n >= 100:
        parts.append(f'{_ONES[n // 100]} HUNDRED')
        n %= 100
    if n >= 20:
        word = _TENS[n // 10]
        if n % 10:
            word += f' {_ONES[n % 10]}'
        parts.append(word)
    elif n > 0:
        parts.append(_ONES[n])
    return ' '.join(parts)


def _amount_in_words(amount: float) -> str:
    """
    Convert a monetary amount (AED) to uppercase English words.

    Examples:
        4357.50  →  "FOUR THOUSAND THREE HUNDRED FIFTY SEVEN AND FIFTY FILS ONLY"
        1000.00  →  "ONE THOUSAND ONLY"
        500.75   →  "FIVE HUNDRED AND SEVENTY FIVE FILS ONLY"
    """
    total_fils = round(amount * 100)
    dirhams = total_fils // 100
    fils     = total_fils % 100

    dirham_words = _int_to_words(dirhams) or 'ZERO'
    if fils:
        fils_words = _int_to_words(fils)
        return f'{dirham_words} AND {fils_words} FILS ONLY'
    return f'{dirham_words} ONLY'


# ── Column helpers ─────────────────────────────────────────────────────────────

def _col_letter_to_num(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n


# ── Date / ref formatting ──────────────────────────────────────────────────────

def _format_ref(year: str, month: str, ref_no: int) -> str:
    return f"{year}/{month}/{ref_no}"


def _format_date(date_str: str) -> str:
    """'DD-MM-YYYY' → 'D/M/YYYY'  (no leading zeros)"""
    day, month, year = date_str.split("-")
    return f"{int(day)}/{int(month)}/{year}"


# ── Merge map ─────────────────────────────────────────────────────────────────

def _build_merge_map(root) -> dict[tuple[int, int], tuple[int, int]]:
    """
    Parse <mergeCells> and return a dict:
        (row, col_num) → (top_left_row, top_left_col_num)
    for every non-top-left cell in every merged range.
    """
    merge_map: dict[tuple[int, int], tuple[int, int]] = {}
    mc_el = root.find(f"{{{_NS_MAIN}}}mergeCells")
    if mc_el is None:
        return merge_map

    for merge in mc_el.findall(f"{{{_NS_MAIN}}}mergeCell"):
        ref = merge.attrib.get("ref", "")
        if ":" not in ref:
            continue
        tl_str, br_str = ref.split(":")
        m1 = re.match(r"([A-Z]+)(\d+)", tl_str)
        m2 = re.match(r"([A-Z]+)(\d+)", br_str)
        if not m1 or not m2:
            continue
        tl_col, tl_row = _col_letter_to_num(m1.group(1)), int(m1.group(2))
        br_col, br_row = _col_letter_to_num(m2.group(1)), int(m2.group(2))

        for r in range(tl_row, br_row + 1):
            for c in range(tl_col, br_col + 1):
                if r != tl_row or c != tl_col:
                    merge_map[(r, c)] = (tl_row, tl_col)

    return merge_map


# ── Cell map ──────────────────────────────────────────────────────────────────

def _build_cell_map(root) -> dict[tuple[int, int], ET.Element]:
    """Return (row_num, col_num) → <c> element for every cell."""
    cell_map: dict[tuple[int, int], ET.Element] = {}
    sheet_data = root.find(f"{{{_NS_MAIN}}}sheetData")
    if sheet_data is None:
        return cell_map

    for row_el in sheet_data.findall(f"{{{_NS_MAIN}}}row"):
        rnum = int(row_el.attrib.get("r", 0))
        for cell_el in row_el.findall(f"{{{_NS_MAIN}}}c"):
            ref = cell_el.attrib.get("r", "")
            m = re.match(r"([A-Z]+)(\d+)", ref)
            if m:
                cnum = _col_letter_to_num(m.group(1))
                cell_map[(rnum, cnum)] = cell_el

    return cell_map


# ── Row map (for height adjustment) ──────────────────────────────────────────

def _build_row_map(root) -> dict[int, ET.Element]:
    """Return row_num → <row> element for every row in sheetData."""
    row_map: dict[int, ET.Element] = {}
    sheet_data = root.find(f"{{{_NS_MAIN}}}sheetData")
    if sheet_data is not None:
        for row_el in sheet_data.findall(f"{{{_NS_MAIN}}}row"):
            rnum = int(row_el.attrib.get("r", 0))
            row_map[rnum] = row_el
    return row_map


def _set_row_height(row_map: dict, row_num: int, height: float) -> None:
    """Set a custom row height (points) directly on the <row> element."""
    row_el = row_map.get(row_num)
    if row_el is not None:
        row_el.set("ht", f"{height:.2f}")
        row_el.set("customHeight", "1")


# ── Cell value setters ────────────────────────────────────────────────────────

def _set_text(cell_el: ET.Element, value: str) -> None:
    """Write a text value using inlineStr (avoids touching sharedStrings.xml)."""
    for child in list(cell_el):
        cell_el.remove(child)
    cell_el.set("t", "inlineStr")
    cell_el.attrib.pop("v", None)
    is_el = ET.SubElement(cell_el, f"{{{_NS_MAIN}}}is")
    t_el  = ET.SubElement(is_el,  f"{{{_NS_MAIN}}}t")
    t_el.text = value
    if value != value.strip():
        t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _set_number(cell_el: ET.Element, value: float | int) -> None:
    """Write a numeric value."""
    for child in list(cell_el):
        cell_el.remove(child)
    cell_el.attrib.pop("t", None)
    v_el = ET.SubElement(cell_el, f"{{{_NS_MAIN}}}v")
    v_el.text = str(int(value)) if float(value) == int(value) else str(value)


def _clear_cell(cell_el: ET.Element) -> None:
    """Remove all value content from a cell, leaving style intact."""
    for child in list(cell_el):
        cell_el.remove(child)
    cell_el.attrib.pop("t", None)


# ── Unified safe-write ────────────────────────────────────────────────────────

def _safe_write(
    cell_map: dict,
    merge_map: dict,
    col_letter: str,
    row: int,
    value,
) -> None:
    """
    Write value to (row, col_letter), redirecting through merge_map to the
    top-left cell of any merged range.  value=None clears; str→text; number→numeric.
    """
    col_num = _col_letter_to_num(col_letter)
    target_row, target_col = merge_map.get((row, col_num), (row, col_num))
    cell_el = cell_map.get((target_row, target_col))
    if cell_el is None:
        return

    if value is None:
        _clear_cell(cell_el)
    elif isinstance(value, str):
        _set_text(cell_el, value)
    else:
        _set_number(cell_el, value)


# ── Item row helpers ──────────────────────────────────────────────────────────

# Max characters that fit in the description area (merged B:G).
# Adjust if your template columns are wider or narrower.
DESC_WRAP_CHARS = 60


def _fmt_qty(qty: float) -> str:
    """Format quantity for the Qty column: 1 → '1-NO', 2+ → 'N-NOS'."""
    n = int(qty) if qty == int(qty) else qty
    return f"{n}-NO" if qty == 1 else f"{n}-NOS"


def _wrap_text(text: str, width: int) -> list[str]:
    """Word-wrap text into lines of at most width characters."""
    if len(text) <= width:
        return [text]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def _clear_item_rows(cell_map, merge_map) -> None:
    """Erase all data in the full item area (rows 20-35, columns A B H J L)."""
    for row in range(ITEM_ROW_START, ITEM_ROW_MAX + 1):
        for col in ("A", "B", "H", "J", "L"):
            _safe_write(cell_map, merge_map, col, row, None)


def _write_multi_item_row(
    cell_map,
    merge_map,
    row_map: dict,
    row: int,
    serial: int,
    description: str,
    quantity: float,
    rate: float,
) -> float:
    """
    Write one item into a single pre-formatted template row.

    The full description is placed in cell B (one cell, Excel wrapText handles
    the visual wrap).  Row height is set to fit the estimated wrapped lines so
    the text is fully visible in PDF output.

    Returns the computed line amount.
    """
    line_amount = round(quantity * rate, 2)
    _safe_write(cell_map, merge_map, "A", row, serial)
    _safe_write(cell_map, merge_map, "B", row, description)
    _safe_write(cell_map, merge_map, "H", row, _fmt_qty(quantity))
    _safe_write(cell_map, merge_map, "J", row, rate)
    _safe_write(cell_map, merge_map, "L", row, line_amount)

    # Set row height to accommodate wrapped description text
    wrapped_lines = max(1, len(_wrap_text(description, DESC_WRAP_CHARS)))
    height = round(wrapped_lines * _ROW_HEIGHT_PER_LINE, 2)
    _set_row_height(row_map, row, height)

    return line_amount


def _write_item_row(
    cell_map,
    merge_map,
    row: int,
    serial: int,
    description: str,
    quantity: float,
    rate: float,
) -> float:
    """Write one item line; returns the computed line amount."""
    line_amount = round(quantity * rate, 2)
    _safe_write(cell_map, merge_map, "A", row, serial)
    _safe_write(cell_map, merge_map, "B", row, description)
    _safe_write(cell_map, merge_map, "H", row, _fmt_qty(quantity))
    _safe_write(cell_map, merge_map, "J", row, rate)
    _safe_write(cell_map, merge_map, "L", row, line_amount)
    return line_amount


def _write_item_block(
    cell_map,
    merge_map,
    start_row: int,
    serial: int,
    description: str,
    quantity: float,
    rate: float,
    max_row: int,
) -> tuple[float, int]:
    """
    Write one item, wrapping its description across consecutive rows.

    start_row  : serial | desc line 1 | qty | rate | amount
    start_row+1:        | desc line 2 |     |      |
    ...

    Returns (line_amount, next_available_row).
    """
    desc_lines = _wrap_text(description, DESC_WRAP_CHARS)
    line_amount = round(quantity * rate, 2)

    # First row — serial, first description line, qty, rate, amount
    _safe_write(cell_map, merge_map, "A", start_row, serial)
    _safe_write(cell_map, merge_map, "B", start_row, desc_lines[0])
    _safe_write(cell_map, merge_map, "H", start_row, _fmt_qty(quantity))
    _safe_write(cell_map, merge_map, "J", start_row, rate)
    _safe_write(cell_map, merge_map, "L", start_row, line_amount)

    current_row = start_row + 1

    # Continuation description lines — description column only
    for line in desc_lines[1:]:
        if current_row > max_row:
            break
        _safe_write(cell_map, merge_map, "B", current_row, line)
        current_row += 1

    return line_amount, current_row


# ── XML serialisation ─────────────────────────────────────────────────────────

def _register_namespaces() -> None:
    ET.register_namespace("",      _NS_MAIN)
    ET.register_namespace("r",     _NS_R)
    ET.register_namespace("mc",    _NS_MC)
    ET.register_namespace("x14ac", _NS_X14AC)


def _serialise_sheet(root) -> bytes:
    body = ET.tostring(root, encoding="unicode")
    xml_decl = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    return (xml_decl + body).encode("utf-8")


# ── Main writer ───────────────────────────────────────────────────────────────

def fill_template(
    request: QuotationCreateRequest,
    ref_no: int,
    output_path: Path,
) -> Path:
    """
    Clone the company Excel template to output_path and fill in the
    quotation data, preserving every image, border, merge, style, and
    formula in the original template unchanged.

    Uses direct zipfile + ElementTree manipulation — embedded images
    (hdphoto1.wdp, image1.jpeg, image2.png) and drawings are never
    processed by openpyxl and therefore cannot be stripped.
    """
    template_path = Path(settings.TEMPLATE_PATH)

    if not template_path.exists():
        raise FileNotFoundError(
            f"Excel template not found: {template_path}\n"
            "Copy your company quotation template to that path and try again."
        )

    # ── 1. Register namespaces (before any ET.fromstring call) ────────────────
    _register_namespaces()

    # ── 2. Read ALL zip entries into memory as raw bytes ─────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(template_path, "r") as zin:
        entries: dict[str, bytes] = {name: zin.read(name) for name in zin.namelist()}
        info_map: dict[str, zipfile.ZipInfo] = {zi.filename: zi for zi in zin.infolist()}

    # ── 3. Parse the sheet XML ────────────────────────────────────────────────
    root = ET.fromstring(entries[_SHEET_ENTRY].decode("utf-8"))

    # ── 4. Build maps ─────────────────────────────────────────────────────────
    merge_map = _build_merge_map(root)
    cell_map  = _build_cell_map(root)
    row_map   = _build_row_map(root)

    # ── 5. Clear stale header / footer data from the template ─────────────────
    for coord in settings.CELLS_TO_CLEAR:
        m = re.match(r"([A-Z]+)(\d+)", coord)
        if m:
            _safe_write(cell_map, merge_map, m.group(1), int(m.group(2)), None)

    # ── 6. Clear all item rows (20-35) ────────────────────────────────────────
    _clear_item_rows(cell_map, merge_map)

    # ── 7. Write header fields (always UPPERCASE) ─────────────────────────────
    _safe_write(cell_map, merge_map, "B", 12, request.client_name.upper())
    # B13 = Attn  (merged B13:G13)
    if request.attn and request.attn.strip():
        _safe_write(cell_map, merge_map, "B", 13, request.attn.strip().upper())
    # B14 = TRN  (merged B14:G14)
    if request.trn and request.trn.strip():
        _safe_write(cell_map, merge_map, "B", 14, request.trn.strip())
    _safe_write(cell_map, merge_map, "K", 14,
                _format_ref(request.year, request.month, ref_no))
    _safe_write(cell_map, merge_map, "K", 16, _format_date(request.date))

    # ── 8. Write item rows ────────────────────────────────────────────────────
    if request.items:
        # ── Multi-item mode ───────────────────────────────────────────────────
        # Each item occupies exactly ONE row from _MULTI_ITEM_ROWS (row 21 is
        # intentionally skipped — its H column is only 1.28pt wide, making qty
        # invisible).  The full description is placed in one B cell and the row
        # height is set to fit the wrapped text so nothing collides or overlaps.
        subtotal = 0.0
        for i, item in enumerate(request.items):
            if i >= len(_MULTI_ITEM_ROWS):
                logger.warning("No more item rows after item %d — remaining items dropped.", i)
                break
            row = _MULTI_ITEM_ROWS[i]
            desc = item.description.upper()
            logger.debug("Item %d → row %d  desc=%r  qty=%s  rate=%s",
                         i + 1, row, desc, item.quantity, item.rate)
            line_amount = _write_multi_item_row(
                cell_map, merge_map, row_map, row,
                serial      = i + 1,
                description = desc,
                quantity    = item.quantity,
                rate        = item.rate,
            )
            subtotal += line_amount

        subtotal = round(subtotal, 2)

    else:
        # ── Single-item mode (HTML form / Telegram) ───────────────────────────
        # Use the same single-row approach for consistency: full description in
        # one B cell with row height set to fit.
        desc = request.description.upper()
        line_amount = _write_multi_item_row(
            cell_map, merge_map, row_map, ITEM_ROW_START,
            serial      = 1,
            description = desc,
            quantity    = request.quantity,
            rate        = request.rate,
        )
        subtotal = round(line_amount, 2)

    # ── 9. Write totals ───────────────────────────────────────────────────────
    tax   = round(request.tax, 2)
    total = round(subtotal + tax, 2)

    _safe_write(cell_map, merge_map, "L", 36, subtotal)
    _safe_write(cell_map, merge_map, "L", 37, tax)
    _safe_write(cell_map, merge_map, "L", 38, total)
    _safe_write(cell_map, merge_map, "L", 40, total)

    # ── 10. Write amount-in-words (C40, merged C40:K40) ───────────────────────
    _safe_write(cell_map, merge_map, "C", 40, _amount_in_words(total))

    # ── 11. Serialise modified sheet XML back to bytes ────────────────────────
    entries[_SHEET_ENTRY] = _serialise_sheet(root)

    # ── 12. Remove calcChain so Excel recalculates on open ───────────────────
    entries.pop("xl/calcChain.xml", None)

    # ── 13. Write new zip — all other entries are byte-identical ─────────────
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            orig_info = info_map.get(name)
            if orig_info is not None:
                zi = zipfile.ZipInfo(filename=orig_info.filename,
                                     date_time=orig_info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, data)
            else:
                zout.writestr(name, data)

    return output_path
