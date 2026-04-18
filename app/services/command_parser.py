"""
services/command_parser.py — Parse natural-language quotation commands.

No external APIs or ML models.  Pure regex + heuristics tuned for the
engineering / fabrication domain.

Supported command shapes
────────────────────────
Single item:
  "Create quotation for Gulf Extrusion fabrication of SS roller 40x120 qty 1 rate 500"
  "Quote for ABB supply of 10mm bolts x5 @ 50 vat 5%"

Multi-item  — explicit "Item N" markers:
  "for Gulf Extrusion
   Item 1 supply of rollers qty 1 rate 450
   Item 2 teflon round bar qty 4 rate 500"

  "Quotation ACME MFG Item 1 hydraulic block DIA 260 2-nos rate 950 Item 2 SS roller rate 400 qty 3"

Parsing flow
────────────
  1. Strip leading action phrase ("create quotation", "quote", …)
  2. Detect "Item N" markers → route to multi-item or single-item handler

  Single-item handler:
    a. Quantity   — "qty N", "N nos", "N pcs", "x N"
    b. Rate       — "rate N", "@ N", "price N", "N/E"
    c. Tax        — "tax N", "vat N%", "N% vat"
    d. Size       — "N x N [unit]", "DIA N", "Ø N"
    e. Client     — first "for / to [words]" up to a fabrication verb or digit
    f. Description— whatever text remains

  Multi-item handler:
    a. Extract client from header text (before the first "Item N" marker)
    b. Parse each item chunk independently for qty / rate / size / description
    c. Compute subtotal, auto-apply 5% VAT, compute total

Financial defaults (single-item)
──────────────────────────────────
  quantity → 1            (if not found)
  rate     → 0            (if not found; a warning is added)
  tax      → 5 % of (qty × rate)   (if not found; a warning is added)
  total    → qty × rate + tax       (always computed here)
  date     → today

Financial defaults (multi-item)
────────────────────────────────
  quantity → 1 per item   (if not found)
  rate     → 0 per item   (warning per item)
  tax      → 5 % of subtotal (always; a note is added)
  total    → subtotal + tax
"""

import re
import logging
from datetime import date as _date

from app.schemas.command import (
    ParsedFields, ParsedItem, FieldConfidence, ParseCommandResponse,
)

logger = logging.getLogger(__name__)


# ── Compiled patterns ─────────────────────────────────────────────────────────

# Strip leading action phrase
_PREFIX = re.compile(
    r"""^
        (?:please\s+)?
        (?:create|make|generate|prepare|new|add)?\s*
        (?:a\s+)?(?:new\s+)?
        (?:quotation|quote|qtn|qt|quo)\s*
        (?:for\s+|to\s+)?           # optional "for/to" attached to prefix
    """,
    re.I | re.X,
)

# Quantity
_QTY = [
    re.compile(r'\bqty\s*[:\-]?\s*(\d+(?:\.\d+)?)',        re.I),
    re.compile(r'\bquantity\s*[:\-]?\s*(\d+(?:\.\d+)?)',   re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*-?nos?\.?\b',           re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*-?pcs?\.?\b',           re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*pieces?\b',             re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*units?\b',              re.I),
    re.compile(r'\bx\s*(\d+(?:\.\d+)?)\b',                 re.I),
]

# Rate / unit price
_RATE = [
    re.compile(r'\brate\s*[:\-]?\s*(\d+(?:\.\d+)?)',                              re.I),
    re.compile(r'\bprice\s*[:\-]?\s*(\d+(?:\.\d+)?)',                             re.I),
    re.compile(r'\bunit\s*price\s*[:\-]?\s*(\d+(?:\.\d+)?)',                      re.I),
    re.compile(r'@\s*(\d+(?:\.\d+)?)',                                             re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*/e\b',                                         re.I),
    re.compile(r'\baed\s*(\d+(?:\.\d+)?)',                                         re.I),
    # "at NNN each / apiece / per piece / per unit" — common spoken form
    re.compile(r'\bat\s+(\d+(?:\.\d+)?)\s*(?:each|apiece|per\s+(?:pc|pcs?|piece|unit|item|no|nos?))\b', re.I),
]

# Tax / VAT  — percentage value OR absolute amount
_TAX = [
    re.compile(r'\b(?:tax|vat)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%', re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*%\s*(?:tax|vat)',             re.I),
    re.compile(r'\b(?:tax|vat)\s*[:\-]?\s*(\d+(?:\.\d+)?)\b',   re.I),
]
_TAX_PCT = re.compile(
    r'\b(?:tax|vat)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*(?:tax|vat)',
    re.I,
)

# Size / dimensions
_SIZE = [
    re.compile(
        r'(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)(?:\s*[xX×]\s*(\d+(?:\.\d+)?))?'
        r'(?:\s*(?:mm|cm|m|inch|"))?\s*(?:(?:long|thick|wide|height|deep|thk)\b)?',
        re.I,
    ),
    re.compile(r'(?:dia(?:meter)?\.?\s*[:\-]?\s*)(\d+(?:\.\d+)?)\s*(?:mm|cm|m)?', re.I),
    re.compile(r'[øØ]\s*(\d+(?:\.\d+)?)\s*(?:mm|cm)?', re.I),
    re.compile(r'(\d+(?:\.\d+)?)\s*mm\s*(?:long|thick|wide|height|deep|thk)\b', re.I),
]

# Words that signal the end of a client name / start of description
_DESC_STARTER = re.compile(
    r'\b(?:fabricat|manufactur|mfg\b|mfg\.|supply|suppli|mak|assembl|repair|'
    r'install|paint|grind|drill|cut|weld|machin|polish|coat|test|deliver|'
    r'provid|finish|process|modif|design|develop|construct|build|erect|'
    r'overhaul|servic|work)',
    re.I,
)

# Client anchor — "for X" or "to X"
_CLIENT_ANCHOR = re.compile(r'^(?:for|to)\s+', re.I)

# "Item N" markers — detect multi-item commands
_ITEM_MARKER_RE = re.compile(r'\bitem\s*\d+\s*[:\-]?\s*', re.I)


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _first_match(patterns: list, text: str):
    for i, pat in enumerate(patterns):
        m = pat.search(text)
        if m:
            return m, i
    return None, -1


def _extract_and_remove(patterns: list, text: str):
    """
    Find first matching pattern, capture its numeric group, remove the full
    match from text.  Returns (value_float, cleaned_text, found).
    """
    m, _ = _first_match(patterns, text)
    if m is None:
        return None, text, False
    val_str = next(g for g in m.groups() if g is not None)
    cleaned = text[:m.start()] + ' ' + text[m.end():]
    return float(val_str), _ws(cleaned), True


def _ws(text: str) -> str:
    """Collapse runs of whitespace."""
    return re.sub(r'\s{2,}', ' ', text).strip()


def _extract_size(text: str):
    """Return (size_string, cleaned_text, found)."""
    for pat in _SIZE:
        m = pat.search(text)
        if m:
            raw = m.group(0).strip()
            cleaned = text[:m.start()] + ' ' + text[m.end():]
            return raw, _ws(cleaned), True
    return '', text, False


def _extract_client(text: str):
    """
    Extract client name from text.

    Strategies (in order):
      A) Text starts with "for X" / "to X" — grab words up to a description
         starter verb, a size pattern, or a digit sequence.
      B) First N capitalised words at the start of the text.
    """
    work = _CLIENT_ANCHOR.sub('', text).strip()

    desc_pos  = _DESC_STARTER.search(work)
    digit_pos = re.search(r'\b\d', work)

    stoppers = [p.start() for p in [desc_pos, digit_pos] if p is not None]
    end      = min(stoppers) if stoppers else len(work)
    candidate = work[:end].strip(' ,.-')

    if candidate and len(candidate.split()) >= 1:
        client = candidate
        remaining = text
        anchor_m = _CLIENT_ANCHOR.match(text)
        search_start = anchor_m.end() if anchor_m else 0
        idx = text.lower().find(candidate.lower(), search_start)
        if idx >= 0:
            remaining = text[:idx] + text[idx + len(candidate):]
        return _ws(client), _ws(remaining), True

    return '', text, False


def _clean_description(text: str) -> str:
    text = re.sub(r'\b(?:for|to)\b', ' ', text, flags=re.I)
    text = re.sub(r'^[\s,.\-:;]+|[\s,.\-:;]+$', '', text)
    return _ws(text)


# ── Multi-item splitting ───────────────────────────────────────────────────────

def _split_items(text: str):
    """
    Detect "Item N" markers and split the command into (header, [item chunks]).

    Returns:
        (header: str, chunks: list[str])   — one or more Item N markers found
        None                               — no markers (single-item command)

    The header is the text before the first "Item N" marker; it contains the
    client name.  Each chunk is the text belonging to that item (between
    consecutive markers, or to end-of-string for the last item).
    """
    markers = list(_ITEM_MARKER_RE.finditer(text))
    if not markers:
        return None

    header = text[:markers[0].start()].strip()
    chunks: list[str] = []
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        chunk = text[m.end():end].strip()
        if chunk:
            chunks.append(chunk)

    return header, chunks


def _parse_item_text(text: str) -> dict:
    """
    Parse qty / rate / size / description from a single item's text.
    Tax is not extracted here — it is a per-quotation value, computed after
    all items are known.
    """
    work = text

    qty,  work, found_qty  = _extract_and_remove(_QTY,  work)
    rate, work, found_rate = _extract_and_remove(_RATE, work)

    if not found_qty:
        qty = 1.0
    if not found_rate:
        rate = 0.0

    size, work, found_size = _extract_size(work)
    description = _clean_description(work)

    return {
        "description": description or text,
        "size":        size,
        "quantity":    qty,
        "rate":        rate,
        "amount":      round(qty * rate, 2),
        "found_qty":   found_qty,
        "found_rate":  found_rate,
        "found_size":  found_size,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def parse_quotation_command(raw: str) -> ParseCommandResponse:
    """
    Parse a natural-language quotation command and return structured fields.

    Routes to multi-item handler if "Item N" markers are detected,
    otherwise falls back to single-item handler.

    Never raises — returns a ParseCommandResponse with warnings if fields
    could not be confidently extracted.
    """
    text = raw.strip()
    work = _PREFIX.sub('', text).strip()

    split = _split_items(work)
    if split is not None:
        return _handle_multi_item(raw, header=split[0], item_chunks=split[1])
    else:
        return _handle_single_item(raw, work)


# ── Single-item handler ───────────────────────────────────────────────────────

def _handle_single_item(raw: str, work: str) -> ParseCommandResponse:
    warnings: list[str] = []

    # ── Quantity ──────────────────────────────────────────────────────────────
    qty, work, found_qty = _extract_and_remove(_QTY, work)
    if not found_qty:
        qty = 1.0
        warnings.append("Quantity not found — defaulted to 1.")

    # ── Rate ──────────────────────────────────────────────────────────────────
    rate, work, found_rate = _extract_and_remove(_RATE, work)
    if not found_rate:
        rate = 0.0
        warnings.append("Rate / unit price not found — set to 0. Add 'rate NNN' to your command.")

    # ── Tax ───────────────────────────────────────────────────────────────────
    tax_pct_m           = _TAX_PCT.search(work)
    tax_raw, work, found_tax = _extract_and_remove(_TAX, work)
    line_amount = round(qty * rate, 2)

    if found_tax:
        tax = round(line_amount * (tax_raw / 100), 2) if tax_pct_m else round(tax_raw, 2)
    else:
        tax = round(line_amount * 0.05, 2)
        warnings.append(
            f"Tax not specified — auto-calculated at 5% = AED {tax:.2f}. "
            "Add 'tax N' or 'vat N%' to override."
        )

    total = round(line_amount + tax, 2)

    # ── Size ──────────────────────────────────────────────────────────────────
    size, work, found_size = _extract_size(work)

    # ── Client ────────────────────────────────────────────────────────────────
    client, work, found_client = _extract_client(work)
    if not found_client:
        warnings.append("Client name not found. Use 'for [CLIENT NAME]' in your command.")

    # ── Description ───────────────────────────────────────────────────────────
    description = _clean_description(work)
    found_description = bool(description)
    if not found_description:
        warnings.append("Description could not be extracted from the command.")

    # ── Date defaults ─────────────────────────────────────────────────────────
    today = _date.today()

    parsed = ParsedFields(
        year        = str(today.year),
        month       = str(today.month).zfill(2),
        date        = today.strftime("%d-%m-%Y"),
        client_name = client or "UNKNOWN",
        description = description or raw,
        size        = size,
        quantity    = qty,
        rate        = rate,
        tax         = tax,
        total       = total,
        items       = [],
    )

    confidence = FieldConfidence(
        client_name = found_client,
        description = found_description,
        size        = found_size,
        quantity    = found_qty,
        rate        = found_rate,
        tax         = found_tax,
    )

    logger.info(
        "Single-item parse | client=%r desc=%r size=%r qty=%s rate=%s tax=%s total=%s",
        parsed.client_name, parsed.description, parsed.size,
        parsed.quantity, parsed.rate, parsed.tax, parsed.total,
    )

    return ParseCommandResponse(
        success    = True,
        parsed     = parsed,
        confidence = confidence,
        warnings   = warnings,
    )


# ── Multi-item handler ────────────────────────────────────────────────────────

def _handle_multi_item(
    raw: str,
    header: str,
    item_chunks: list[str],
) -> ParseCommandResponse:
    warnings: list[str] = []
    today = _date.today()

    # ── 1. Extract client from the header (text before "Item 1") ─────────────
    # The header never contains "Item N" text, so client extraction is clean.
    client, _, found_client = _extract_client(header)
    if not found_client:
        # Fall back: strip "for/to" and use the whole header as client name
        client = _CLIENT_ANCHOR.sub('', header).strip()
        found_client = bool(client)
    if not found_client:
        warnings.append(
            "Client name not found. Put the client name before 'Item 1': "
            "'for [CLIENT] Item 1 ...'"
        )
        client = "UNKNOWN"

    # ── 2. Parse each item chunk ──────────────────────────────────────────────
    parsed_items: list[ParsedItem] = []
    for idx, chunk in enumerate(item_chunks, start=1):
        item = _parse_item_text(chunk)

        if not item["found_rate"]:
            warnings.append(
                f"Rate not found for Item {idx} "
                f"('{item['description'][:30]}…') — set to 0. "
                "Add 'rate NNN' to that item."
            )

        parsed_items.append(ParsedItem(
            description = item["description"],
            size        = item["size"],
            quantity    = item["quantity"],
            rate        = item["rate"],
            amount      = item["amount"],
        ))

    # ── 3. Totals (always 5% VAT for multi-item) ──────────────────────────────
    subtotal = round(sum(i.amount for i in parsed_items), 2)
    tax      = round(subtotal * 0.05, 2)
    total    = round(subtotal + tax, 2)
    warnings.append(
        f"VAT auto-calculated at 5% of subtotal "
        f"AED {subtotal:.2f} = AED {tax:.2f}."
    )

    # ── 4. Build response — first item fills legacy single-item fields ─────────
    first = parsed_items[0]

    parsed = ParsedFields(
        year        = str(today.year),
        month       = str(today.month).zfill(2),
        date        = today.strftime("%d-%m-%Y"),
        client_name = client,
        description = first.description,
        size        = first.size,
        quantity    = first.quantity,
        rate        = first.rate,
        tax         = tax,
        total       = total,
        items       = parsed_items,
    )

    confidence = FieldConfidence(
        client_name = found_client,
        description = all(bool(i.description) for i in parsed_items),
        size        = any(bool(i.size) for i in parsed_items),
        quantity    = True,
        rate        = all(i.rate > 0 for i in parsed_items),
        tax         = False,   # always auto-calculated for multi-item
    )

    logger.info(
        "Multi-item parse | client=%r items=%d subtotal=%s tax=%s total=%s",
        parsed.client_name, len(parsed_items), subtotal, tax, total,
    )

    return ParseCommandResponse(
        success    = True,
        parsed     = parsed,
        confidence = confidence,
        warnings   = warnings,
    )
