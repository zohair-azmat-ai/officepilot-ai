"""
services/bank_ledger_parser.py — Parse Telegram bank ledger commands.

Incoming:
  online payment received PARTY amount N
  payment received PARTY amount N          (no "invoice" keyword)
  cheque received PARTY amount N
  cash received PARTY amount N

Outgoing:
  cheque withdrawn N [for NOTES]
  expense DESCRIPTION amount N
  bank payment PARTY amount N

Queries:
  bank balance
  bank statement MONTH YEAR [pdf]
  bank statement MM YYYY [pdf]
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


@dataclass
class BankEntry:
    transaction_type: str   # "Incoming" | "Outgoing"
    mode: str               # "Online" | "Cheque" | "Cash" | "Bank Transfer" | "Bank Payment" | "Expense" | "Cheque Withdrawn"
    party: str = ""
    description: str = ""
    amount_in: float = 0.0
    amount_out: float = 0.0
    notes: str = ""


@dataclass
class BankStatement:
    month: int
    year: int
    as_pdf: bool = False


def _extract_amount(text: str) -> tuple[float, str]:
    """
    Find and remove the amount from text.  Looks for 'amount N', 'aed N', then
    falls back to the last standalone number.  Returns (amount, cleaned_text).
    """
    m = re.search(r"(?:amount|amt|aed|dhs?)\s+([\d,]+(?:\.\d{1,2})?)", text, re.I)
    if m:
        amt = float(m.group(1).replace(",", ""))
        text = (text[: m.start()] + " " + text[m.end() :]).strip()
        return amt, _clean(text)

    nums = list(re.finditer(r"\b([\d,]+(?:\.\d{1,2})?)\b", text))
    if nums:
        last = nums[-1]
        amt = float(last.group(1).replace(",", ""))
        text = (text[: last.start()] + " " + text[last.end() :]).strip()
        return amt, _clean(text)

    return 0.0, _clean(text)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


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
        amt, party = _extract_amount(m.group(1))
        return BankEntry(
            transaction_type="Incoming",
            mode="Online",
            party=party,
            description="Online Payment Received",
            amount_in=amt,
        )

    # ── Cheque received ───────────────────────────────────────────────────────
    m = re.match(r"^cheque\s+received\s+(.+)", text, re.I)
    if m:
        amt, party = _extract_amount(m.group(1))
        return BankEntry(
            transaction_type="Incoming",
            mode="Cheque",
            party=party,
            description="Cheque Received",
            amount_in=amt,
        )

    # ── Cash received ─────────────────────────────────────────────────────────
    m = re.match(r"^cash\s+received\s+(.+)", text, re.I)
    if m:
        amt, party = _extract_amount(m.group(1))
        return BankEntry(
            transaction_type="Incoming",
            mode="Cash",
            party=party,
            description="Cash Received",
            amount_in=amt,
        )

    # ── Payment received (no invoice → bank incoming) ─────────────────────────
    m = re.match(r"^payment\s+received\s+(.+)", text, re.I)
    if m and "invoice" not in t and " inv " not in t:
        tail = re.sub(r"^(?:for\s+|from\s+)", "", m.group(1), flags=re.I)
        amt, party = _extract_amount(tail)
        return BankEntry(
            transaction_type="Incoming",
            mode="Bank Transfer",
            party=party,
            description="Payment Received",
            amount_in=amt,
        )

    # ── Cheque withdrawn ──────────────────────────────────────────────────────
    m = re.match(r"^cheque\s+withdrawn\s+(.+)", text, re.I)
    if m:
        tail = m.group(1).strip()
        amt, rest = _extract_amount(tail)
        notes_m = re.search(r"\bfor\s+(.+)", rest, re.I)
        notes = _clean(notes_m.group(1)) if notes_m else ""
        if notes_m:
            rest = rest[: notes_m.start()].strip()
        return BankEntry(
            transaction_type="Outgoing",
            mode="Cheque Withdrawn",
            party=_clean(rest),
            description="Cheque Withdrawn",
            amount_out=amt,
            notes=notes,
        )

    # ── Expense ───────────────────────────────────────────────────────────────
    m = re.match(r"^expense\s+(.+)", text, re.I)
    if m:
        amt, rest = _extract_amount(m.group(1))
        desc = _clean(rest) or "Expense"
        return BankEntry(
            transaction_type="Outgoing",
            mode="Expense",
            party="",
            description=desc.title(),
            amount_out=amt,
            notes=desc.title(),
        )

    # ── Bank payment ──────────────────────────────────────────────────────────
    m = re.match(r"^bank\s+payment\s+(.+)", text, re.I)
    if m:
        amt, party = _extract_amount(m.group(1))
        return BankEntry(
            transaction_type="Outgoing",
            mode="Bank Payment",
            party=party,
            description="Bank Payment",
            amount_out=amt,
        )

    return None


def _parse_statement(text: str) -> "BankStatement | None":
    as_pdf    = bool(re.search(r"\bpdf\b", text, re.I))
    stripped  = re.sub(r"\bpdf\b", "", text, flags=re.I).strip()

    year_m = _YEAR_RE.search(stripped)
    if not year_m:
        return None
    year    = int(year_m.group(1))
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
