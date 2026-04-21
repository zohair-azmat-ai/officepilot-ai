"""
services/invoice_writer.py — Fill the company invoice template.

Uses the same ZIP+ElementTree approach as excel_writer.py to preserve
embedded images (logo, stamp) in the template.

Cell layout assumptions (adjust constants below to match your template):
  B12        ← Client name      (merged B12:G12)
  B13        ← Attn             (merged B13:G13, optional)
  B14        ← LPO number       (merged B14:G14, optional)
  K14        ← Invoice number   (merged K14:L14)
  K15        ← DO number        (merged K15:L15, optional)
  K16        ← Date             (merged K16:L16)
  Rows 20, 22-35 ← Items       (row 21 skipped — H21 is 1.28pt wide)
  L36        ← Subtotal
  L37        ← VAT
  L38        ← Total
  C40        ← Amount in words  (merged C40:K40)
  L40        ← Total copy       (merged L40:L41)
"""

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.services.excel_writer import (
    _build_merge_map, _build_cell_map, _build_row_map,
    _safe_write, _set_row_height,
    _fmt_qty, _wrap_text, _amount_in_words,
    _register_namespaces, _serialise_sheet,
    DESC_WRAP_CHARS, _ROW_HEIGHT_PER_LINE,
)

logger = logging.getLogger(__name__)

_SHEET_ENTRY = "xl/worksheets/sheet1.xml"

# Item rows — row 21 intentionally skipped (H21 is only 1.28pt wide)
_INV_ITEM_ROWS    = [20] + list(range(22, 36))
_INV_ITEM_ROW_MAX = 35

# Cells to clear before writing (stale template data)
_INV_CELLS_TO_CLEAR = ["B13", "B14", "K15", "B21"]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class InvoiceItem:
    description: str
    quantity:    float
    rate:        float
    amount:      float = 0.0


@dataclass
class InvoiceRequest:
    client_name: str
    date:        str        # DD-MM-YYYY
    invoice_no:  str        # INV-YYYY-XXXX
    year:        str
    month:       str
    lpo:         str = ""
    do_no:       str = ""
    attn:        str = ""
    trn:         str = ""
    items:       list[InvoiceItem] = field(default_factory=list)
    tax:         float = 0.0
    total:       float = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_date(date_str: str) -> str:
    """DD-MM-YYYY → D/M/YYYY (no leading zeros, matching quotation style)."""
    day, month, year = date_str.split("-")
    return f"{int(day)}/{int(month)}/{year}"


def _write_inv_item_row(
    cell_map, merge_map, row_map,
    row: int, serial: int,
    description: str, quantity: float, rate: float,
) -> float:
    line_amount = round(quantity * rate, 2)
    _safe_write(cell_map, merge_map, "A", row, serial)
    _safe_write(cell_map, merge_map, "B", row, description)
    _safe_write(cell_map, merge_map, "H", row, _fmt_qty(quantity))
    _safe_write(cell_map, merge_map, "J", row, rate)
    _safe_write(cell_map, merge_map, "L", row, line_amount)
    wrapped = max(1, len(_wrap_text(description, DESC_WRAP_CHARS)))
    _set_row_height(row_map, row, round(wrapped * _ROW_HEIGHT_PER_LINE, 2))
    return line_amount


# ── Main writer ───────────────────────────────────────────────────────────────

def fill_invoice_template(request: InvoiceRequest, output_path: Path) -> Path:
    """
    Clone the invoice template to output_path and fill in all data fields.
    Raises FileNotFoundError if the template is missing.
    """
    template_path = Path(settings.INVOICE_TEMPLATE_PATH)
    if not template_path.exists():
        raise FileNotFoundError(
            f"Invoice template not found: {template_path}\n"
            "Place your invoice Excel template at that path and try again."
        )

    _register_namespaces()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(template_path, "r") as zin:
        entries:  dict[str, bytes]          = {n: zin.read(n) for n in zin.namelist()}
        info_map: dict[str, zipfile.ZipInfo] = {zi.filename: zi for zi in zin.infolist()}

    root      = ET.fromstring(entries[_SHEET_ENTRY].decode("utf-8"))
    merge_map = _build_merge_map(root)
    cell_map  = _build_cell_map(root)
    row_map   = _build_row_map(root)

    # ── Clear stale template data ─────────────────────────────────────────────
    for coord in _INV_CELLS_TO_CLEAR:
        m = re.match(r"([A-Z]+)(\d+)", coord)
        if m:
            _safe_write(cell_map, merge_map, m.group(1), int(m.group(2)), None)

    for row in range(20, _INV_ITEM_ROW_MAX + 1):
        for col in ("A", "B", "H", "J", "L"):
            _safe_write(cell_map, merge_map, col, row, None)

    # ── Header fields ─────────────────────────────────────────────────────────
    _safe_write(cell_map, merge_map, "B", 12, request.client_name.upper())
    if request.attn:
        _safe_write(cell_map, merge_map, "B", 13, request.attn.strip().upper())
    if request.lpo:
        _safe_write(cell_map, merge_map, "B", 14, request.lpo.strip())
    _safe_write(cell_map, merge_map, "K", 14, request.invoice_no)
    if request.do_no:
        _safe_write(cell_map, merge_map, "K", 15, request.do_no.strip())
    _safe_write(cell_map, merge_map, "K", 16, _fmt_date(request.date))

    # ── Item rows ─────────────────────────────────────────────────────────────
    subtotal = 0.0
    for i, item in enumerate(request.items):
        if i >= len(_INV_ITEM_ROWS):
            logger.warning("No more invoice item rows after item %d — dropped.", i)
            break
        row = _INV_ITEM_ROWS[i]
        logger.debug("Invoice item %d → row %d  desc=%r  qty=%s  rate=%s",
                     i + 1, row, item.description, item.quantity, item.rate)
        subtotal += _write_inv_item_row(
            cell_map, merge_map, row_map, row,
            serial=i + 1,
            description=item.description.upper(),
            quantity=item.quantity,
            rate=item.rate,
        )

    subtotal = round(subtotal, 2)
    tax      = round(request.tax, 2)
    total    = round(subtotal + tax, 2)

    # ── Totals ────────────────────────────────────────────────────────────────
    _safe_write(cell_map, merge_map, "L", 36, subtotal)
    _safe_write(cell_map, merge_map, "L", 37, tax)
    _safe_write(cell_map, merge_map, "L", 38, total)
    _safe_write(cell_map, merge_map, "L", 40, total)
    _safe_write(cell_map, merge_map, "C", 40, _amount_in_words(total))

    # ── Serialise ─────────────────────────────────────────────────────────────
    entries[_SHEET_ENTRY] = _serialise_sheet(root)
    entries.pop("xl/calcChain.xml", None)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            orig = info_map.get(name)
            if orig is not None:
                zi = zipfile.ZipInfo(filename=orig.filename, date_time=orig.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, data)
            else:
                zout.writestr(name, data)

    return output_path
