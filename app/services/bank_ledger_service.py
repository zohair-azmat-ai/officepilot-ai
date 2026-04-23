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


def _next_row(ws) -> int:
    """Return the row number for the next entry (one after the last non-empty data row)."""
    last = 1  # row 1 is always the header
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if any(v is not None for v in row):
            last = i
    return last + 1


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
    Append a row to the correct year's bank ledger and return the new balance.
    If date_str is provided it determines which year's workbook receives the entry.
    All text fields are stored uppercase for consistency.
    """
    today = _date.today()
    if date_str:
        parsed_d = _parse_date(date_str)
        year = parsed_d.year if parsed_d else today.year
    else:
        year     = today.year
        date_str = today.strftime("%d-%m-%Y")

    wb, ws, path = _open_or_create(year)
    prev_bal = _last_balance(ws)
    new_bal  = round(prev_bal + amount_in - amount_out, 2)

    row_num = _next_row(ws)
    ws.cell(row_num, _C_DATE).value  = date_str
    ws.cell(row_num, _C_TYPE).value  = transaction_type
    ws.cell(row_num, _C_MODE).value  = mode
    ws.cell(row_num, _C_PARTY).value = party.upper()       if party       else ""
    ws.cell(row_num, _C_DESC).value  = description.upper() if description else ""
    ws.cell(row_num, _C_IN).value    = amount_in  if amount_in  else None
    ws.cell(row_num, _C_OUT).value   = amount_out if amount_out else None
    ws.cell(row_num, _C_BAL).value   = new_bal
    ws.cell(row_num, _C_NOTES).value = notes.upper() if notes else ""
    _style_data_row(ws, row_num, transaction_type == "Incoming")

    wb.save(path)
    logger.info(
        "Bank entry: %s %s  party=%r  in=%.2f  out=%.2f  bal=%.2f  row=%d",
        transaction_type, mode, party, amount_in, amount_out, new_bal, row_num,
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
    Generate a print-ready A4 portrait statement Excel (and optionally PDF).

    Fixed row layout (never uses ws.append so row numbers are deterministic):
      Row 1  : Title bar
      Row 2  : Spacer
      Rows 3-6 : Summary (Opening Balance / Total In / Total Out / Closing Balance)
      Row 7  : Spacer
      Row 8  : Table header
      Row 9+ : Transaction rows

    Print settings: A4 portrait, fit-to-1-page-wide, fit-to-1-page-tall when
    ≤ 25 data rows (forces single-page PDF for small/test data).

    Returns dict with keys:
      xlsx_path, pdf_path, opening_balance, total_in, total_out,
      closing_balance, row_count, month_name
    """
    from app.services.pdf_export import export_to_pdf
    from openpyxl.worksheet.properties import PageSetupProperties

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

    # ── Output path ───────────────────────────────────────────────────────────
    stmt_folder = Path(settings.BANK_LEDGER_BASE_PATH) / str(year) / str(month).zfill(2)
    stmt_folder.mkdir(parents=True, exist_ok=True)
    today_str = _date.today().strftime("%d-%m-%Y")
    xlsx_path = stmt_folder / f"{today_str} BANK STATEMENT {month_name.upper()} {year}.xlsx"

    # ── Build workbook ────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{month_name[:3]} {year}"

    # ── A4 portrait print setup ───────────────────────────────────────────────
    ws.page_setup.paperSize   = 9            # A4
    ws.page_setup.orientation = "portrait"
    ws.page_margins.left   = 0.5
    ws.page_margins.right  = 0.5
    ws.page_margins.top    = 0.75
    ws.page_margins.bottom = 0.75
    ws.page_margins.header = 0.3
    ws.page_margins.footer = 0.3
    ws.print_options.horizontalCentered = True

    # Fit to page: always 1 page wide; 1 page tall for small data
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth  = 1
    ws.page_setup.fitToHeight = 1 if len(period_rows) <= 25 else 0

    # ── Column widths (A4 portrait proportions) ───────────────────────────────
    # Total ≈ 119 units; fitToWidth=1 scales automatically if wider than page
    _STMT_WIDTHS = [12, 10, 14, 16, 20, 11, 11, 13, 12]   # A-I
    for i, w in enumerate(_STMT_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Row 1: Title ──────────────────────────────────────────────────────────
    ws.merge_cells("A1:I1")
    tc = ws.cell(1, 1)
    tc.value     = f"BANK STATEMENT  {month_name.upper()} {year}"
    tc.font      = Font(bold=True, size=16, color="FFFFFF")
    tc.fill      = _HDR_FILL
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 40

    # ── Row 2: Spacer ─────────────────────────────────────────────────────────
    ws.row_dimensions[2].height = 6

    # ── Rows 3-6: Summary block ───────────────────────────────────────────────
    _SUMM_FILL    = PatternFill("solid", fgColor="EBF3FB")
    _CLOSING_FILL = PatternFill("solid", fgColor="D0E8F5")
    _SUMM_THIN    = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"),  bottom=Side(style="thin"),
    )

    summary_items = [
        ("Opening Balance:", f"AED {opening_balance:,.2f}", False),
        ("Total In:",        f"AED {total_in:,.2f}",        False),
        ("Total Out:",       f"AED {total_out:,.2f}",       False),
        ("Closing Balance:", f"AED {closing:,.2f}",         True),
    ]
    for r_idx, (label, val, is_closing) in enumerate(summary_items, 3):
        fill = _CLOSING_FILL if is_closing else _SUMM_FILL
        ws.merge_cells(f"A{r_idx}:D{r_idx}")
        ws.merge_cells(f"E{r_idx}:I{r_idx}")

        lc = ws.cell(r_idx, 1)
        lc.value     = label
        lc.font      = Font(bold=True, size=11)
        lc.fill      = fill
        lc.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        lc.border    = _SUMM_THIN

        vc = ws.cell(r_idx, 5)
        vc.value     = val
        vc.font      = Font(bold=is_closing, size=11,
                            color="1F4E79" if is_closing else "000000")
        vc.fill      = fill
        vc.alignment = Alignment(horizontal="right", vertical="center", indent=1)
        vc.border    = _SUMM_THIN
        ws.row_dimensions[r_idx].height = 22

    # ── Row 7: Spacer ─────────────────────────────────────────────────────────
    ws.row_dimensions[7].height = 6

    # ── Row 8: Table header ────────────────────────────────────────────────────
    _HDR_ROW = 8
    for c_idx, h in enumerate(_HEADERS, 1):
        cell = ws.cell(_HDR_ROW, c_idx)
        cell.value     = h
        cell.font      = _HDR_FONT
        cell.fill      = _HDR_FILL
        cell.alignment = _CENTER
        cell.border    = _THIN
    ws.row_dimensions[_HDR_ROW].height = 22

    # ── Rows 9+: Transaction data ──────────────────────────────────────────────
    for i, r in enumerate(period_rows):
        row_n = 9 + i
        row_data = [
            r["date"], r["type"], r["mode"], r["party"], r["description"],
            r["in"]  or None,
            r["out"] or None,
            r["balance"] if r["balance"] else None,
            r["notes"],
        ]
        for c_idx, val in enumerate(row_data, 1):
            ws.cell(row_n, c_idx).value = val
        _style_data_row(ws, row_n, r["type"] == "Incoming")
        ws.row_dimensions[row_n].height = 18

    # ── Print area and repeating header ───────────────────────────────────────
    last_row = 8 + len(period_rows)
    ws.print_area        = f"A1:I{last_row}"
    ws.print_title_rows  = f"{_HDR_ROW}:{_HDR_ROW}"

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
