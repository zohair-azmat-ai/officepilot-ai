"""
services/ocr_parser.py — OCR-based invoice field extraction.

Image OCR  : pytesseract + Pillow (with preprocessing)
PDF (text) : pdfplumber  (no poppler needed; covers digital invoice PDFs)
PDF (scan) : pdf2image + pytesseract  (needs poppler; optional)

Template-aware extraction strategy:
─────────────────────────────────────────────────────────────────────────────
OUR TEMPLATE (Dar Al Salam / DTW letterhead):
  invoice  → "Ref" / "Ref No" label → "No." label
  date     → "Date:" label near top-right
  customer → "CO. NAME" label → "Mr./M/s" prefix  (NEVER our own company)
  amount   → Grand Total / Total (bottom-up) → bottom-right tier
  lpo      → explicit L.P.O. / LPO field only

GENERIC INVOICE:
  invoice  → "Ref:" / "Invoice No:" labels → first numeric token on inv line
  date     → "Date:" label → any DD/MM/YYYY pattern
  customer → "CO. NAME" / "Client:" / "Bill To:" → company-memory scan
  amount   → Grand Total → Total (bottom-up) → largest decimal in bottom 30%
  lpo      → LPO/Purchase Order keyword + digit value only
─────────────────────────────────────────────────────────────────────────────
"""

import re as _re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Tesseract: LSTM engine (OEM 3), uniform block (PSM 6)
_TESS_CFG     = r"--oem 3 --psm 6"
# Looser PSM for small cropped regions
_TESS_CFG_RAW = r"--oem 3 --psm 11"


# ── Our company identity ──────────────────────────────────────────────────────
# If any of these appear in the top 500 chars of OCR text, this is our invoice.
# Values that must NEVER be returned as the customer company.

_OUR_TEMPLATE_RE = _re.compile(
    r"\b(?:dar\s+al\s+salam(?:\s+eng(?:ineering)?(?:\s+turning\s+works)?)?|dtw)\b",
    _re.I,
)


def _is_our_template(text: str) -> bool:
    return bool(_OUR_TEMPLATE_RE.search(text[:500]))


def _is_our_company(name: str) -> bool:
    return bool(_OUR_TEMPLATE_RE.match(name.strip()))


# ── Image preprocessing ───────────────────────────────────────────────────────

def _preprocess(img):
    """
    Full preprocessing pipeline for PIL Images.

    Order matters:
      1. Fix EXIF/OSD rotation so text is upright before OCR
      2. Grayscale — colour is noise for Tesseract
      3. Auto-contrast stretch — handles dark/washed-out photos
      4. Upscale — Tesseract loves ≥ 300 DPI; target 2400px on long edge
      5. Unsharp mask — crisp edges without haloing large blobs
      6. Sharpen pass — extra clarity for small fonts
    """
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    img = ImageOps.exif_transpose(img)
    img = img.convert("L")

    # Rotation correction via Tesseract OSD (handles 90/180/270° phone photos)
    img = _fix_rotation(img)

    # Stretch histogram to fill 0–255
    img = ImageOps.autocontrast(img, cutoff=2)

    # Upscale if too small for reliable OCR
    w, h = img.size
    long_edge = max(w, h)
    if long_edge < 2400:
        scale = 2400 / long_edge
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img = ImageEnhance.Contrast(img).enhance(1.8)
    # UnsharpMask preserves fine strokes better than double SHARPEN
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _fix_rotation(img):
    """
    Detect 90°/180°/270° rotation via Tesseract OSD and correct it.
    Silently skips if OSD fails (e.g. too little text for detection).
    """
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(
            img,
            output_type=pytesseract.Output.DICT,
            config="--psm 0 -c min_characters_to_try=5",
        )
        angle = int(osd.get("rotate", 0))
        if angle:
            from PIL import Image
            # Tesseract 'rotate' is the angle needed to make text upright
            img = img.rotate(angle, expand=True, fillcolor=255)
    except Exception:
        pass
    return img


# ── Region OCR (image only) ───────────────────────────────────────────────────

def _ocr_zone(img, top_pct: float, bot_pct: float,
              left_pct: float, right_pct: float) -> str:
    """OCR a proportional crop of a preprocessed PIL Image."""
    import pytesseract
    w, h = img.size
    box = (int(w * left_pct), int(h * top_pct),
           int(w * right_pct), int(h * bot_pct))
    region = img.crop(box)
    return pytesseract.image_to_string(region, config=_TESS_CFG_RAW)


# ── Text extraction ───────────────────────────────────────────────────────────

def _ocr_image(path: Path) -> "tuple[str, object]":
    """Return (full_text, preprocessed_img) for an image file."""
    import pytesseract
    from PIL import Image
    img = _preprocess(Image.open(path))
    return pytesseract.image_to_string(img, config=_TESS_CFG), img


def _extract_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n".join(pages).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("pdfplumber failed: %s", exc)

    try:
        from pdf2image import convert_from_path
        import pytesseract
        pages = convert_from_path(str(path))
        return "\n".join(
            pytesseract.image_to_string(_preprocess(p), config=_TESS_CFG)
            for p in pages
        )
    except ImportError:
        raise RuntimeError(
            "Could not extract text from PDF.\n"
            "Install pdfplumber:  pip install pdfplumber\n"
            "Or for scanned PDFs: pip install pdf2image  (needs poppler)"
        )


def extract_text(file_path: "str | Path") -> str:
    """Return raw OCR/extracted text from an image or PDF file."""
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        return _extract_pdf(path)
    text, _ = _ocr_image(path)
    return text


# ── Shared helpers ────────────────────────────────────────────────────────────

def _rightmost_number(line: str) -> "float | None":
    for tok in reversed(_re.findall(r"[\d,]+\.?\d*", line)):
        try:
            val = float(tok.replace(",", ""))
            if val > 0:
                return val
        except ValueError:
            pass
    return None


def _clean(s: str) -> str:
    """Strip OCR noise: leading = signs, punctuation, extra whitespace."""
    return _re.sub(r"^[\s=:|\-\.]+", "", s).strip()


# ── Invoice number ────────────────────────────────────────────────────────────

def _is_date_like(val: str) -> bool:
    return bool(_re.match(r"^\d{1,2}[/\-]\d{1,2}", val))


def _parse_invoice_number(text: str, our_template: bool = False) -> "str | None":
    """
    Our template  → "Ref" / "Ref No" label (same line OR next line), then "No." label.
    Generic       → "Ref:" / "Invoice No:" labels, then "No." as last resort.
    Last resort   → any standalone 3-6 digit number in the top third of text.
    Rejects date-like values and tokens with no digits.
    """
    candidates: list[str] = []
    lines = text.splitlines()

    # "Ref" label — same-line value
    for m in _re.finditer(
        r"\bref(?:erence)?(?:\s*no\.?)?\s*[:#\-]?\s*([A-Z0-9][\w\-/]{1,20})",
        text, _re.I,
    ):
        val = _clean(m.group(1))
        if not _is_date_like(val) and _re.search(r"\d", val):
            candidates.append(val)

    # "Ref" label alone on its line — value is on the NEXT line
    for i, line in enumerate(lines):
        if _re.search(r"\bref(?:erence)?(?:\s*no\.?)?\s*[:#\-]?\s*$", line.strip(), _re.I):
            if i + 1 < len(lines):
                nxt = _clean(lines[i + 1].strip())
                if nxt and _re.search(r"\d", nxt) and not _is_date_like(nxt):
                    candidates.append(nxt)

    # "No." label — used by our template for the invoice serial
    for m in _re.finditer(r"\bno\.?\s*:?\s*([0-9A-Z][\w\-/]{0,15})", text, _re.I):
        val = _clean(m.group(1))
        if not _is_date_like(val) and _re.search(r"\d{3,}", val):
            candidates.append(val)

    # Generic "Invoice / Inv" label
    if not our_template:
        for m in _re.finditer(
            r"\b(?:invoice|inv)[\s]*(?:no\.?|number|#)?[\s:#]*([A-Z0-9][\w\-/]{2,20})",
            text, _re.I,
        ):
            val = _clean(m.group(1))
            if not _is_date_like(val) and _re.search(r"\d", val):
                candidates.append(val)

    if candidates:
        return candidates[0]

    # Last resort: any standalone 3-6 digit number in the top third of the text
    top_lines = lines[: max(1, len(lines) // 3)]
    for line in top_lines:
        for m in _re.finditer(r"\b(\d{3,6})\b", line):
            val = m.group(1)
            if not _is_date_like(val):
                return val

    return None


# ── Date ──────────────────────────────────────────────────────────────────────

def _parse_date(text: str) -> "str | None":
    """
    1st: "Date:" label — matches our template's labelled date field.
    2nd: generic DD/MM/YYYY or YYYY-MM-DD patterns anywhere.
    Returns DD-MM-YYYY.
    """
    m = _re.search(
        r"\bdate\s*[:#\-]?\s*"
        r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}"
        r"|\d{4}[\/\-]\d{2}[\/\-]\d{2})",
        text, _re.I,
    )
    if m:
        return m.group(1).replace("/", "-")

    for pat in (
        r"\b(\d{2}[\/\-]\d{2}[\/\-]\d{4})\b",
        r"\b(\d{4}[\/\-]\d{2}[\/\-]\d{2})\b",
    ):
        m2 = _re.search(pat, text)
        if m2:
            return m2.group(1).replace("/", "-")

    return None


# ── Amount ────────────────────────────────────────────────────────────────────

_RE_GRAND = _re.compile(
    r"\b(?:grand\s+total|total\s+amount|net\s+amount|amount\s+due"
    r"|total\s+incl|total\s+vat|invoice\s+total)\b",
    _re.I,
)
_RE_TOTAL = _re.compile(r"\btotal\b", _re.I)


_RE_VAT = _re.compile(r"\bv\.?a\.?t\.?\b", _re.I)


def _parse_total_amount(text: str) -> "float | None":
    """
    Bottom-up with four priority tiers:
      1. Explicit "Grand Total / Total Amount / Net Amount" labels
      2. Plain "TOTAL" or "TOTAL :" label — lowest instance avoids subtotal rows
      3. When VAT line is present: last decimal number in bottom 30%
         (handles the pattern: subtotal / VAT / FINAL — last number wins)
      4. Largest decimal in bottom 30% (final fallback)
    """
    lines = text.splitlines()

    # Tier 1: explicit grand-total labels
    for i in range(len(lines) - 1, -1, -1):
        if _RE_GRAND.search(lines[i]):
            val = _rightmost_number(lines[i])
            if val is None and i + 1 < len(lines):
                val = _rightmost_number(lines[i + 1])
            if val:
                return val

    # Tier 2: plain "TOTAL" / "TOTAL :" label (lowest occurrence = final total)
    for i in range(len(lines) - 1, -1, -1):
        if _RE_TOTAL.search(lines[i]):
            val = _rightmost_number(lines[i])
            if val:
                return val

    # Collect all decimals in bottom 30%
    bottom = lines[int(len(lines) * 0.7):]
    candidates: list[float] = []
    for line in bottom:
        for tok in _re.findall(r"[\d,]+\.\d{2}", line):
            try:
                candidates.append(float(tok.replace(",", "")))
            except ValueError:
                pass

    if not candidates:
        return None

    # Tier 3: VAT detected → last (bottom-most) decimal is the post-VAT total
    has_vat = bool(_RE_VAT.search(text))
    if has_vat:
        return candidates[-1]   # last number printed = amount after VAT

    # Tier 4: no VAT → largest decimal (safest proxy for the total)
    return max(candidates)


# ── LPO ───────────────────────────────────────────────────────────────────────

def _parse_lpo_strict(text: str) -> "str | None":
    """
    Only extract LPO when an explicit keyword + digit-containing value follows.
    Rejects pure-word values like "Box", "N/A".
    """
    m = _re.search(
        r"\b(?:l\.?p\.?o\.?|purchase\s+order|p\.?o\.?)\s*"
        r"(?:no\.?|number|#)?\s*[:\-]?\s*"
        r"([A-Z0-9][\w\-]{1,20})",
        text, _re.I,
    )
    if m:
        val = m.group(1).strip()
        if _re.search(r"\d", val):
            return val
    return None


# ── Customer / company detection ──────────────────────────────────────────────

# Matches "CO. NAME:", "Mr./M/s", "M/s", "Client:", "Bill To:" etc.
_RE_CO_NAME   = _re.compile(r"co\.?\s*name\s*[:\-]?\s*(.+)", _re.I)
_RE_MR_MS     = _re.compile(
    r"(?:mr\.?\s*/\s*m\s*/?\s*s\.?|m\s*/\s*s\.?|mr\.?)\s+(.+)", _re.I
)
_RE_CUST_LABEL = _re.compile(
    r"(?:client|customer|bill\s+to|sold\s+to|ship\s+to|to\s*:|attn)\s*[:\-]?\s*(.+)",
    _re.I,
)


def _best_customer_name(val: str) -> "str | None":
    """Return val if it looks like a valid company name and is not our own company."""
    val = _clean(val)
    if len(val) < 4 or val.isdigit() or ":" in val:
        return None
    if _is_our_company(val):
        return None
    return val


def _customer_from_our_template(text: str) -> "str | None":
    """
    Extract customer name from our Dar Al Salam / DTW invoice template.
    Priority: "CO. NAME" → "Mr./M/s" prefix → generic client labels.
    Skips our own company name in all cases.
    """
    for line in text.splitlines():
        m = _RE_CO_NAME.search(line)
        if m:
            c = _best_customer_name(m.group(1))
            if c:
                return c

    for line in text.splitlines():
        m = _RE_MR_MS.search(line)
        if m:
            c = _best_customer_name(m.group(1))
            if c:
                return c

    # Generic labels as last resort
    for line in text.splitlines():
        m = _RE_CUST_LABEL.search(line)
        if m:
            c = _best_customer_name(m.group(1))
            if c:
                return c

    return None


def detect_company(text: str) -> "str | None":
    """
    For our invoice template: use template-specific customer extraction,
    never return our own company name.
    Generic fallback: scan first 600 chars against company memory.
    """
    from app.services.company_memory import lookup as _lookup, _normalize, _score

    our = _is_our_template(text)

    if our:
        raw_name = _customer_from_our_template(text)
        if raw_name:
            # Try to match against memory; use raw name if no confident match
            hits = _lookup(raw_name, max_results=1)
            if hits:
                sc = _score(_normalize(raw_name), set(_normalize(raw_name).split()),
                            hits[0].company_name)
                if sc >= 45:
                    return hits[0].company_name
            # Return raw OCR text as-is — better than wrong mapping
            return raw_name

    # Generic path: scan top of text against company memory
    snippet = text[:600]
    for line in snippet.splitlines():
        line = line.strip()
        if len(line) < 4 or _is_our_company(line):
            continue
        hits = _lookup(line, max_results=1)
        if hits:
            sc = _score(_normalize(line), set(_normalize(line).split()), hits[0].company_name)
            if sc >= 60:
                return hits[0].company_name

    return None


# ── Region-based amount extraction (image only) ───────────────────────────────

def _amount_from_bottom_right(img) -> "float | None":
    """Bottom-right zone — totals always appear here on our template."""
    zone_text = _ocr_zone(img, top_pct=0.65, bot_pct=1.0,
                          left_pct=0.50, right_pct=1.0)
    return _parse_total_amount(zone_text)


def _invoice_no_from_top_left(img) -> "str | None":
    """
    Top-left zone — Ref / No. fields live here on our DTW template.
    (Date is top-right; we keep the zones separate.)
    """
    zone_text = _ocr_zone(img, top_pct=0.0, bot_pct=0.30,
                          left_pct=0.0, right_pct=0.50)
    return _parse_invoice_number(zone_text, our_template=True)


def _date_from_top_right(img) -> "str | None":
    """Top-right zone — Date field lives here on our DTW template."""
    zone_text = _ocr_zone(img, top_pct=0.0, bot_pct=0.30,
                          left_pct=0.50, right_pct=1.0)
    return _parse_date(zone_text)


def _customer_from_mid_left(img, our_template: bool) -> "str | None":
    """Middle-left zone — customer block on our template."""
    zone_text = _ocr_zone(img, top_pct=0.20, bot_pct=0.55,
                          left_pct=0.0, right_pct=0.60)
    if our_template:
        return _customer_from_our_template(zone_text)
    return None


# ── Field parsing ─────────────────────────────────────────────────────────────

def parse_fields(text: str) -> dict:
    """
    Extract invoice fields from raw OCR text.
    Auto-detects our template and applies template-specific rules.
    Returns dict with keys: invoice, date, amount, lpo  (all may be None).
    """
    our = _is_our_template(text)
    return {
        "invoice": _parse_invoice_number(text, our_template=our),
        "date":    _parse_date(text),
        "amount":  _parse_total_amount(text),
        "lpo":     _parse_lpo_strict(text),
    }


# ── Public entry points ───────────────────────────────────────────────────────

def extract_from_file(file_path: "str | Path") -> "tuple[str, dict]":
    """
    Run OCR / text extraction and return (raw_text, parsed_fields).
    parsed_fields keys: invoice, date, amount, lpo, company.

    For image files, runs additional zone-level OCR to improve accuracy on
    our Dar Al Salam / DTW invoice template.
    """
    path = Path(file_path)
    is_image = path.suffix.lower() not in (".pdf",)

    if is_image:
        text, img = _ocr_image(path)
    else:
        text = _extract_pdf(path)
        img  = None

    our = _is_our_template(text)
    fields = parse_fields(text)

    # For image files, supplement with zone OCR for higher accuracy
    if img is not None:
        # Invoice number: top-LEFT zone (Ref / No. live there on our template)
        if not fields["invoice"]:
            zone_inv = _invoice_no_from_top_left(img)
            if zone_inv:
                fields["invoice"] = zone_inv
                logger.debug("Invoice no from top-left zone: %s", zone_inv)

        # Date: top-RIGHT zone if full-text missed it
        if not fields["date"]:
            zone_date = _date_from_top_right(img)
            if zone_date:
                fields["date"] = zone_date
                logger.debug("Date from top-right zone: %s", zone_date)

        # Amount: bottom-right zone — always prefer this for our template
        zone_amt = _amount_from_bottom_right(img)
        if zone_amt and (fields["amount"] is None or abs(zone_amt - fields["amount"]) > 1):
            logger.debug(
                "Amount corrected by zone OCR: full=%s → zone=%s",
                fields["amount"], zone_amt,
            )
            fields["amount"] = zone_amt

    fields["company"] = detect_company(text)

    # If company came back as our own name, clear it (shows as not detected → user corrects)
    if fields.get("company") and _is_our_company(fields["company"]):
        fields["company"] = None

    logger.info(
        "OCR result (our_template=%s): inv=%s  date=%s  amount=%s  lpo=%s  company=%s",
        our, fields["invoice"], fields["date"], fields["amount"],
        fields["lpo"], fields["company"],
    )

    return text, fields
