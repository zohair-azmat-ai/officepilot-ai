"""
services/invoice_writer.py — Company-specific invoice template filler.

Supports two company templates:
  quant_gulf       → QUANT GULF LLC template
  gulf_extrusions  → GULF EXTRUSIONS LLC template

Cell layouts are derived from the actual template XML structure.
Uses the same ZIP+ElementTree approach as excel_writer.py to preserve
embedded images (logo, stamp) in the template.
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


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class InvoiceItem:
    description: str
    quantity:    float
    rate:        float
    amount:      float = 0.0


@dataclass
class InvoiceRequest:
    company_key: str          # "quant_gulf" or "gulf_extrusions"
    client_name: str          # used in reply messages; template already has it
    date:        str          # DD-MM-YYYY
    invoice_no:  int          # plain sequential number (e.g. 8794)
    lpo:         str = ""
    do_no:       str = ""
    attn:        str = ""
    trn:         str = ""
    items:       list[InvoiceItem] = field(default_factory=list)
    tax:         float = 0.0
    total:       float = 0.0


# ── Per-company layout descriptors ────────────────────────────────────────────
#
# item_rows     : ordered list of row numbers usable for line items
# item_row_max  : last row to clear (inclusive) before writing
# clear_cols    : columns to zero out before writing items
# per_line_tax  : True → write G/H/I/M per item (Gulf Extrusions)
#                 False → write A/B/E/F/J per item (Quant Gulf)

_QUANT_GULF_LAYOUT = {
    "template_attr":   "QUANT_GULF_INVOICE_TEMPLATE_PATH",
    "display_name":    "QUANT GULF LLC",
    "seq_keyword":     "quant",          # keyword to filter filenames during seq scan
    "seq_floor":       8793,             # never go below this number + 1
    "invoice_no_cell": ("B", 12),
    "date_cell":       ("F", 12),
    "date_sep":        "-",             # date written as DD-MM-YYYY in cell
    "do_cell":         ("E", 18),
    "do_prefix":       "                         D.O NO  :-       ",
    "lpo_cell":        ("J", 19),
    "item_rows":       [23] + list(range(24, 36)),  # 13 slots (rows 23-35)
    "item_row_max":    35,
    "clear_cols":      ["A", "B", "E", "F", "J"],
    "serial_col":      "A",
    "desc_col":        "B",
    "qty_col":         "E",
    "rate_col":        "F",
    "amount_col":      "J",
    "subtotal_cell":   ("J", 37),
    "vat_cell":        ("J", 38),
    "total_cell":      ("J", 39),
    "words_cell":      ("B", 39),
    "per_line_tax":    False,
}

_GULF_EXTRUSIONS_LAYOUT = {
    "template_attr":   "GULF_EXTRUSIONS_INVOICE_TEMPLATE_PATH",
    "display_name":    "GULF EXTRUSIONS LLC",
    "seq_keyword":     "extrusion",      # keyword to filter filenames during seq scan
    "seq_floor":       8834,
    "invoice_no_cell": ("B", 12),
    "date_cell":       ("I", 12),
    "date_sep":        "/",             # date written as DD/MM/YYYY in cell
    "do_cell":         ("I", 17),
    "do_prefix":       "DO :-                  ",
    "lpo_cell":        ("M", 18),
    "item_rows":       list(range(22, 39)),  # 17 slots (rows 22-38)
    "item_row_max":    38,
    "clear_cols":      ["A", "B", "E", "F", "G", "H", "I", "M"],
    "serial_col":      "A",
    "desc_col":        "B",
    "qty_col":         "E",
    "rate_col":        "F",
    "amount_col":      "G",   # excl VAT
    "tax_rate_col":    "H",
    "tax_amt_col":     "I",
    "total_col":       "M",   # G + I per line
    "subtotal_cell":   ("M", 40),
    "vat_cell":        ("M", 41),
    "total_cell":      ("M", 42),
    "words_cell":      ("B", 42),
    "per_line_tax":    True,
}

_LAYOUTS: dict[str, dict] = {
    "quant_gulf":      _QUANT_GULF_LAYOUT,
    "gulf_extrusions": _GULF_EXTRUSIONS_LAYOUT,
}


# ── Item-row writers ──────────────────────────────────────────────────────────

def _write_item_simple(cell_map, merge_map, row_map, layout: dict,
                       row: int, serial: int,
                       description: str, quantity: float, rate: float) -> float:
    """Write one item row for Quant Gulf (no per-line tax). Returns line amount."""
    amount = round(quantity * rate, 2)
    _safe_write(cell_map, merge_map, layout["serial_col"],  row, serial)
    _safe_write(cell_map, merge_map, layout["desc_col"],    row, description)
    _safe_write(cell_map, merge_map, layout["qty_col"],     row, _fmt_qty(quantity))
    _safe_write(cell_map, merge_map, layout["rate_col"],    row, rate)
    _safe_write(cell_map, merge_map, layout["amount_col"],  row, amount)
    wrapped = max(1, len(_wrap_text(description, DESC_WRAP_CHARS)))
    _set_row_height(row_map, row, round(wrapped * _ROW_HEIGHT_PER_LINE, 2))
    return amount


def _write_item_tax(cell_map, merge_map, row_map, layout: dict,
                    row: int, serial: int,
                    description: str, quantity: float, rate: float) -> float:
    """Write one item row for Gulf Extrusions (per-line VAT). Returns excl-VAT amount."""
    amount_excl = round(quantity * rate, 2)
    tax_amt     = round(amount_excl * 0.05, 2)
    total_line  = round(amount_excl + tax_amt, 2)
    _safe_write(cell_map, merge_map, layout["serial_col"],   row, serial)
    _safe_write(cell_map, merge_map, layout["desc_col"],     row, description)
    _safe_write(cell_map, merge_map, layout["qty_col"],      row, _fmt_qty(quantity))
    _safe_write(cell_map, merge_map, layout["rate_col"],     row, rate)
    _safe_write(cell_map, merge_map, layout["amount_col"],   row, amount_excl)
    _safe_write(cell_map, merge_map, layout["tax_rate_col"], row, 0.05)
    _safe_write(cell_map, merge_map, layout["tax_amt_col"],  row, tax_amt)
    _safe_write(cell_map, merge_map, layout["total_col"],    row, total_line)
    wrapped = max(1, len(_wrap_text(description, DESC_WRAP_CHARS)))
    _set_row_height(row_map, row, round(wrapped * _ROW_HEIGHT_PER_LINE, 2))
    return amount_excl


# ── Main writer ───────────────────────────────────────────────────────────────

def fill_invoice_template(request: InvoiceRequest, output_path: Path) -> Path:
    """
    Clone the company-specific invoice template to output_path and fill all fields.
    Raises ValueError for unknown company_key; FileNotFoundError if template missing.
    """
    layout = _LAYOUTS.get(request.company_key)
    if layout is None:
        raise ValueError(
            f"Unknown company_key: {request.company_key!r}. "
            "Use 'quant_gulf' or 'gulf_extrusions'."
        )

    template_path = Path(getattr(settings, layout["template_attr"]))
    if not template_path.exists():
        raise FileNotFoundError(
            f"Invoice template not found: {template_path}\n"
            f"Set {layout['template_attr']} in .env or place the template file there."
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

    # ── Clear item rows ────────────────────────────────────────────────────────
    for row in range(layout["item_rows"][0], layout["item_row_max"] + 1):
        for col in layout["clear_cols"]:
            _safe_write(cell_map, merge_map, col, row, None)

    # ── Invoice number ─────────────────────────────────────────────────────────
    inv_col, inv_row = layout["invoice_no_cell"]
    _safe_write(cell_map, merge_map, inv_col, inv_row, request.invoice_no)

    # ── Date ──────────────────────────────────────────────────────────────────
    sep = layout["date_sep"]
    date_val = f"DATE :-{request.date.replace('-', sep)}"
    date_col, date_row = layout["date_cell"]
    _safe_write(cell_map, merge_map, date_col, date_row, date_val)

    # ── DO number ─────────────────────────────────────────────────────────────
    do_col, do_row = layout["do_cell"]
    do_text = layout["do_prefix"] + (request.do_no.strip() if request.do_no else "")
    _safe_write(cell_map, merge_map, do_col, do_row, do_text)

    # ── LPO number ────────────────────────────────────────────────────────────
    lpo_col, lpo_row = layout["lpo_cell"]
    if request.lpo:
        try:
            lpo_val: int | str = int(request.lpo.replace(",", "").strip())
        except ValueError:
            lpo_val = request.lpo.strip()
        _safe_write(cell_map, merge_map, lpo_col, lpo_row, lpo_val)
    else:
        _safe_write(cell_map, merge_map, lpo_col, lpo_row, None)

    # ── Item rows ──────────────────────────────────────────────────────────────
    subtotal   = 0.0
    item_rows  = layout["item_rows"]
    write_item = _write_item_tax if layout["per_line_tax"] else _write_item_simple

    for i, item in enumerate(request.items):
        if i >= len(item_rows):
            logger.warning("No more invoice item rows after item %d — dropped.", i)
            break
        row = item_rows[i]
        logger.debug("Invoice item %d → row %d  desc=%r  qty=%s  rate=%s",
                     i + 1, row, item.description, item.quantity, item.rate)
        subtotal += write_item(
            cell_map, merge_map, row_map, layout, row,
            serial=i + 1,
            description=item.description.upper(),
            quantity=item.quantity,
            rate=item.rate,
        )

    subtotal = round(subtotal, 2)
    tax      = round(subtotal * 0.05, 2)
    total    = round(subtotal + tax, 2)

    # ── Totals ────────────────────────────────────────────────────────────────
    sub_col, sub_row = layout["subtotal_cell"]
    vat_col, vat_row = layout["vat_cell"]
    tot_col, tot_row = layout["total_cell"]
    wrd_col, wrd_row = layout["words_cell"]
    _safe_write(cell_map, merge_map, sub_col, sub_row, subtotal)
    _safe_write(cell_map, merge_map, vat_col, vat_row, tax)
    _safe_write(cell_map, merge_map, tot_col, tot_row, total)
    _safe_write(cell_map, merge_map, wrd_col, wrd_row, _amount_in_words(total))

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
