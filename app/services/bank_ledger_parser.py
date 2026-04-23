"""
services/bank_ledger_parser.py — Parse Telegram bank ledger commands.

Incoming:
  online payment received PARTY amount N [noted NOTES] [date DD-MM-YYYY]
  payment received PARTY amount N          (no "invoice" keyword)
  cheque received PARTY amount N [noted NOTES] [date DD-MM-YYYY]
  cash received PARTY amount N [noted NOTES] [date DD-MM-YYYY]

Outgoing:
  cheque withdrawn N [for NOTES] [date DD-MM-YYYY]
  expense DESCRIPTION amount N [date DD-MM-YYYY]
  bank payment PARTY amount N [noted NOTES] [date DD-MM-YYYY]

Queries:
  bank balance
  bank statement MONTH YEAR [pdf]
  bank statement MM YYYY [pdf]

Extraction order for incoming/outgoing:
  1. Strip 'date DD-MM-YYYY'  → date_str
  2. Strip 'noted/note/reason ANYTHING'  → notes
  3. Strip 'amount N' (or last number)   → amount
  4. Remaining text                      → party / description
"""

import re
from dataclasses import dataclass


_MONTH_MAP: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_YEAR_RE = re.compile(r"\b(20[2-9]\d)\b")

# 'date DD-MM-YYYY'  |  'date YYYY-MM-DD'  |  'date DD/MM/YYYY'
_DATE_TAG_RE = re.compile(
    r"\bdate\s+(\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b",
    re.I,
)

# 'noted ANYTHING'  |  'note ANYTHING'  |  'reason ANYTHING'
# Captures everything after the keyword to end-of-string.
_NOTES_TAG_RE = re.compile(r"\b(?:noted?|reason)\s+(.+)", re.I)


@dataclass
class BankEntry:
    transaction_type: str   # "Incoming" | "Outgoing"
    mode: str               # "Online" | "Cheque" | "Cash" | "Bank Transfer" |
                            # "Bank Payment" | "Expense" | "Cheque Withdrawn"
    party: str = ""
    description: str = ""
    amount_in: float = 0.0
    amount_out: float = 0.0
    notes: str = ""
    date_str: str = ""      # DD-MM-YYYY or YYYY-MM-DD; empty → service uses today


@dataclass
class BankStatement:
    month: int
    year: int
    as_pdf: bool = False


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _extract_date_tag(text: str) -> tuple[str, str]:
    """Remove 'date DD-MM-YYYY' from text. Returns (date_str_or_empty, cleaned_text)."""
    m = _DATE_TAG_RE.search(text)
    if m:
        return m.group(1), _clean(text[: m.start()] + " " + text[m.end() :])
    return "", _clean(text)


def _extract_notes_tag(text: str) -> tuple[str, str]:
    """Remove 'noted/note/reason ANYTHING' from text. Returns (notes_or_empty, cleaned_text)."""
    m = _NOTES_TAG_RE.search(text)
    if m:
        return _clean(m.group(1)), _clean(text[: m.start()] + " " + text[m.end() :])
    return "", _clean(text)


def _extract_amount(text: str) -> tuple[float, str]:
    """
    Find and remove the amount from text.  Looks for 'amount N', 'aed N', then
    falls back to the last standalone number.  Returns (amount, cleaned_text).
    """
    m = re.search(r"(?:amount|amt|aed|dhs?)\s+([\d,]+(?:\.\d{1,2})?)", text, re.I)
    if m:
        amt = float(m.group(1).replace(",", ""))
        return amt, _clean(text[: m.start()] + " " + text[m.end() :])

    nums = list(re.finditer(r"\b([\d,]+(?:\.\d{1,2})?)\b", text))
    if nums:
        last = nums[-1]
        amt  = float(last.group(1).replace(",", ""))
        return amt, _clean(text[: last.start()] + " " + text[last.end() :])

    return 0.0, _clean(text)


def _parse_incoming(tail: str, mode: str, description: str) -> BankEntry:
    """
    Parse the tail of an incoming command (everything after the command prefix).
    Extraction order: date → notes → amount → party (remainder).
    """
    date_str, tail = _extract_date_tag(tail)
    notes,    tail = _extract_notes_tag(tail)
    amount, party  = _extract_amount(tail)
    # Strip accidental leading "for"/"from" in party (e.g. "payment received for COMPANY")
    party = re.sub(r"^(?:for\s+|from\s+)", "", party, flags=re.I)
    return BankEntry(
        transaction_type="Incoming",
        mode=mode,
        party=_clean(party),
        description=description,
        amount_in=amount,
        notes=notes,
        date_str=date_str,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def parse_bank_command(text: str) -> "BankEntry | BankStatement | str | None":
    """
    Parse a bank ledger command.

    Returns:
      BankEntry      — incoming or outgoing transaction
      BankStatement  — statement request
      "balance"      — balance query
      None           — not a recognised bank command
    """
    t = _clean(text).lower()

    # ── Balance query ─────────────────────────────────────────────────────────
    if re.match(r"^bank\s+balance", t):
        return "balance"

    # ── Statement query ───────────────────────────────────────────────────────
    if re.match(r"^bank\s+statement", t):
        return _parse_statement(text)

    # ── Online payment received ───────────────────────────────────────────────
    m = re.match(r"^online\s+payment\s+received\s+(.+)", text, re.I)
    if m:
        return _parse_incoming(m.group(1), "Online", "Online Payment Received")

    # ── Cheque received ───────────────────────────────────────────────────────
    m = re.match(r"^cheque\s+received\s+(.+)", text, re.I)
    if m:
        return _parse_incoming(m.group(1), "Cheque", "Cheque Received")

    # ── Cash received ─────────────────────────────────────────────────────────
    m = re.match(r"^cash\s+received\s+(.+)", text, re.I)
    if m:
        return _parse_incoming(m.group(1), "Cash", "Cash Received")

    # ── Payment received (no invoice → bank incoming) ─────────────────────────
    m = re.match(r"^payment\s+received\s+(.+)", text, re.I)
    if m and "invoice" not in t and " inv " not in t:
        tail = re.sub(r"^(?:for\s+|from\s+)", "", m.group(1), flags=re.I)
        return _parse_incoming(tail, "Bank Transfer", "Payment Received")

    # ── Cheque withdrawn ──────────────────────────────────────────────────────
    m = re.match(r"^cheque\s+withdrawn\s+(.+)", text, re.I)
    if m:
        tail             = m.group(1).strip()
        date_str, tail   = _extract_date_tag(tail)
        amt, rest        = _extract_amount(tail)
        notes_m          = re.search(r"\bfor\s+(.+)", rest, re.I)
        notes            = _clean(notes_m.group(1)) if notes_m else ""
        if notes_m:
            rest = rest[: notes_m.start()].strip()
        return BankEntry(
            transaction_type="Outgoing",
            mode="Cheque Withdrawn",
            party=_clean(rest),
            description="Cheque Withdrawn",
            amount_out=amt,
            notes=notes,
            date_str=date_str,
        )

    # ── Expense ───────────────────────────────────────────────────────────────
    m = re.match(r"^expense\s+(.+)", text, re.I)
    if m:
        tail           = m.group(1).strip()
        date_str, tail = _extract_date_tag(tail)
        amt, rest      = _extract_amount(tail)
        desc           = _clean(rest) or "Expense"
        return BankEntry(
            transaction_type="Outgoing",
            mode="Expense",
            party="",
            description=desc.title(),
            amount_out=amt,
            notes=desc.title(),
            date_str=date_str,
        )

    # ── Bank payment ──────────────────────────────────────────────────────────
    m = re.match(r"^bank\s+payment\s+(.+)", text, re.I)
    if m:
        tail           = m.group(1).strip()
        date_str, tail = _extract_date_tag(tail)
        notes, tail    = _extract_notes_tag(tail)
        amt, party     = _extract_amount(tail)
        return BankEntry(
            transaction_type="Outgoing",
            mode="Bank Payment",
            party=_clean(party),
            description="Bank Payment",
            amount_out=amt,
            notes=notes,
            date_str=date_str,
        )

    return None


def _parse_statement(text: str) -> "BankStatement | None":
    as_pdf   = bool(re.search(r"\bpdf\b", text, re.I))
    stripped = re.sub(r"\bpdf\b", "", text, flags=re.I).strip()

    year_m = _YEAR_RE.search(stripped)
    if not year_m:
        return None
    year     = int(year_m.group(1))
    stripped = (stripped[: year_m.start()] + stripped[year_m.end() :]).strip()

    # Remove "bank statement" prefix
    stripped = re.sub(r"^bank\s+statement\s*", "", stripped, flags=re.I).strip()

    tok = stripped.lower()
    if tok in _MONTH_MAP:
        return BankStatement(month=_MONTH_MAP[tok], year=year, as_pdf=as_pdf)
    m = re.match(r"^0?(\d{1,2})$", tok)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return BankStatement(month=month, year=year, as_pdf=as_pdf)
    return None
