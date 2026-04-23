"""
services/bank_ledger_service.py — Bank account ledger: Excel storage, balance, statements.

Storage layout:
  BANK_LEDGER_BASE_PATH/
    BANK_LEDGER_2026.xlsx    ← one workbook per year, sheet "Transactions"
    2026/04/                 ← generated statement files
      DD-MM-YYYY BANK STATEMENT APRIL 2026.xlsx
      DD-MM-YYYY BANK STATEMENT APRIL 2026.pdf

Sheet columns:
  A  Date          B  Type       C  Mode         D  Party/Company
  E  Description   F  In         G  Out          H  Balance    I  Notes
"""

import logging
from datetime import date as _date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.config import settings

logger = logging.getLogger(__name__)

# ── Column indices (1-based, for openpyxl) ────────────────────────────────────
_C_DATE  = 1   # A
_C_TYPE  = 2   # B
_C_MODE  = 3   # C
_C_PARTY = 4   # D
_C_DESC  = 5   # E
_C_IN    = 6   # F
_C_OUT   = 7   # G
_C_BAL   = 8   # H
_C_NOTES = 9   # I

_HEADERS = ["Date", "Type", "Mode", "Party/Company",
            "Description", "In", "Out", "Balance", "Notes"]

_MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]

# ── Styles ────────────────────────────────────────────────────────────────────
_HDR_FILL  = PatternFill("solid", fgColor="1F4E79")
_HDR_FONT  = Font(bold=True, color="FFFFFF", size=11)
_IN_FILL   = PatternFill("solid", fgColor="E8F5E9")   # light green
_OUT_FILL  = PatternFill("solid", fgColor="FFEBEE")   # light red
_THIN      = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
_CENTER = Alignment(horizontal="center", vertical="center")
_LEFT   = Alignment(horizontal="left",   vertical="center", wrap_text=True)
_RIGHT  = Alignment(horizontal="right",  vertical="center")
_MONEY  = '#,##0.00'

_COL_WIDTHS = [14, 12, 18, 25, 30, 14, 14, 16, 20]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ledger_path(year: int) -> Path:
    base = Path(settings.BANK_LEDGER_BASE_PATH)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"BANK_LEDGER_{year}.xlsx"


def _style_header_row(ws, row: int = 1) -> None:
    for col in range(1, len(_HEADERS) + 1):
        cell = ws.cell(row, col)
        cell.font      = _HDR_FONT
        cell.fill      = _HDR_FILL
        cell.alignment = _CENTER
        cell.border    = _THIN


def _style_data_row(ws, row: int, is_incoming: bool) -> None:
    fill = _IN_FILL if is_incoming else _OUT_FILL
    for col in range(1, len(_HEADERS) + 1):
        cell = ws.cell(row, col)
        cell.fill   = fill
        cell.border = _THIN
        if col in (_C_IN, _C_OUT, _C_BAL):
            cell.number_format = _MONEY
            cell.alignment     = _RIGHT
        elif col == _C_DATE:
            cell.alignment = _CENTER
        else:
            cell.alignment = _LEFT


def _open_or_create(year: int):
    path = _ledger_path(year)
    if path.exists():
        wb = openpyxl.load_workbook(path)
        ws = wb["Transactions"] if "Transactions" in wb.sheetnames else wb.active
        return wb, ws, path

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(_HEADERS)
    _style_header_row(ws, 1)
    ws.row_dimensions[1].height = 20
    for i, w in enumerate(_COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    wb.save(path)
    return wb, ws, path


def _last_balance(ws) -> float:
    last = 0.0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[_C_BAL - 1] is not None:
            try:
                last = float(row[_C_BAL - 1])
            except (TypeError, ValueError):
                pass
    return last


def _parse_date(s: str) -> "_date | None":
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            pass
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def add_bank_entry(
    transaction_type: str,
    mode: str,
    party: str = "",
    description: str = "",
    amount_in: float = 0.0,
    amount_out: float = 0.0,
    notes: str = "",
    date_str: "str | None" = None,
) -> float:
    """
    Append a row to the current year's bank ledger and return the new balance.
    All text fields are stored uppercase for consistency.
    """
    today    = _date.today()
    year     = today.year
    date_str = date_str or today.strftime("%d-%m-%Y")

    wb, ws, path = _open_or_create(year)
    prev_bal = _last_balance(ws)
    new_bal  = round(prev_bal + amount_in - amount_out, 2)

    row_num = ws.max_row + 1
    ws.append([
        date_str,
        transaction_type,
        mode,
        party.upper()       if party       else "",
        description.upper() if description else "",
        amount_in  if amount_in  else None,
        amount_out if amount_out else None,
        new_bal,
        notes.upper() if notes else "",
    ])
    _style_data_row(ws, row_num, transaction_type == "Incoming")

    wb.save(path)
    logger.info(
        "Bank entry: %s %s  party=%r  in=%.2f  out=%.2f  bal=%.2f",
        transaction_type, mode, party, amount_in, amount_out, new_bal,
    )
    return new_bal


def get_bank_balance(year: "int | None" = None) -> float:
    """Return the running balance from the last row of the ledger."""
    year = year or _date.today().year
    path = _ledger_path(year)
    if not path.exists():
        return 0.0
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Transactions"] if "Transactions" in wb.sheetnames else wb.active
    return _last_balance(ws)


def generate_bank_statement(
    month: int,
    year: int,
    as_pdf: bool = False,
) -> dict:
    """
    Generate a formatted statement Excel for the given month/year.

    Returns dict with keys:
      xlsx_path, pdf_path, opening_balance, total_in, total_out,
      closing_balance, row_count, month_name
    """
    from app.services.pdf_export import export_to_pdf

    month_name  = _MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
    ledger_path = _ledger_path(year)

    # ── Read all rows from this year's ledger ─────────────────────────────────
    all_rows: list[dict] = []
    if ledger_path.exists():
        wb_src = openpyxl.load_workbook(ledger_path, data_only=True)
        ws_src = wb_src["Transactions"] if "Transactions" in wb_src.sheetnames else wb_src.active
        for row in ws_src.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            all_rows.append({
                "date":        str(row[_C_DATE  - 1] or "").strip(),
                "type":        str(row[_C_TYPE  - 1] or ""),
                "mode":        str(row[_C_MODE  - 1] or ""),
                "party":       str(row[_C_PARTY - 1] or ""),
                "description": str(row[_C_DESC  - 1] or ""),
                "in":          float(row[_C_IN   - 1] or 0),
                "out":         float(row[_C_OUT  - 1] or 0),
                "balance":     float(row[_C_BAL  - 1] or 0),
                "notes":       str(row[_C_NOTES - 1] or ""),
            })

    # Opening balance = balance of last row before this month
    opening_balance = 0.0
    for r in all_rows:
        d = _parse_date(r["date"])
        if d and (d.year < year or (d.year == year and d.month < month)):
            opening_balance = r["balance"]

    period_rows = [
        r for r in all_rows
        if (d := _parse_date(r["date"])) and d.year == year and d.month == month
    ]

    total_in  = round(sum(r["in"]  for r in period_rows), 2)
    total_out = round(sum(r["out"] for r in period_rows), 2)
    closing   = round(opening_balance + total_in - total_out, 2)

    # ── Build statement workbook ──────────────────────────────────────────────
    stmt_folder = Path(settings.BANK_LEDGER_BASE_PATH) / str(year) / str(month).zfill(2)
    stmt_folder.mkdir(parents=True, exist_ok=True)

    today_str  = _date.today().strftime("%d-%m-%Y")
    xlsx_path  = stmt_folder / f"{today_str} BANK STATEMENT {month_name.upper()} {year}.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{month_name[:3]} {year}"

    for i, w in enumerate(_COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Title row
    ws.merge_cells("A1:I1")
    tc = ws["A1"]
    tc.value     = f"BANK STATEMENT — {month_name.upper()} {year}"
    tc.font      = Font(bold=True, size=14, color="FFFFFF")
    tc.fill      = _HDR_FILL
    tc.alignment = _CENTER
    ws.row_dimensions[1].height = 30

    # Summary block
    _SUMMARY_FILL = PatternFill("solid", fgColor="EBF3FB")
    for i, (label, val, bold) in enumerate([
        ("Opening Balance:", f"AED {opening_balance:,.2f}", False),
        ("Total In:",        f"AED {total_in:,.2f}",        False),
        ("Total Out:",       f"AED {total_out:,.2f}",       False),
        ("Closing Balance:", f"AED {closing:,.2f}",         True),
    ], 2):
        ws.merge_cells(f"A{i}:D{i}")
        ws.merge_cells(f"E{i}:I{i}")
        lc, vc = ws.cell(i, 1), ws.cell(i, 5)
        lc.value = label
        vc.value = val
        lc.font  = Font(bold=True,  size=11)
        vc.font  = Font(bold=bold, size=11)
        lc.fill  = vc.fill = _SUMMARY_FILL
        lc.alignment = _LEFT
        vc.alignment = _LEFT

    ws.append([""] * 9)   # blank separator

    # Header row
    hdr_row = ws.max_row + 1
    ws.append(_HEADERS)
    _style_header_row(ws, hdr_row)

    # Data rows
    for r in period_rows:
        ws.append([
            r["date"], r["type"], r["mode"], r["party"], r["description"],
            r["in"]  or None,
            r["out"] or None,
            r["balance"] if r["balance"] else None,
            r["notes"],
        ])
        _style_data_row(ws, ws.max_row, r["type"] == "Incoming")

    wb.save(xlsx_path)
    logger.info("Bank statement Excel: %s  rows=%d", xlsx_path, len(period_rows))

    # ── PDF export ────────────────────────────────────────────────────────────
    pdf_path = None
    if as_pdf:
        result = export_to_pdf(xlsx_path)
        if result["status"] == "created":
            pdf_path = result["pdf_path"]
            logger.info("Bank statement PDF: %s", pdf_path)

    return {
        "xlsx_path":       xlsx_path,
        "pdf_path":        pdf_path,
        "opening_balance": opening_balance,
        "total_in":        total_in,
        "total_out":       total_out,
        "closing_balance": closing,
        "row_count":       len(period_rows),
        "month_name":      month_name,
    }
