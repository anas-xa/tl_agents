"""File parsing for manual uploads (E4-S3 Q387): CSV, XLSX (zipfile + xml, no dependency) and text-based PDF.

Normalisation: detect UTF-8 / Windows-1256, NFC, strip bidirectional control characters, convert Arabic-Indic
digits to Western for comparison (the original text is kept), parse amounts and dates. Pure functions.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
import zipfile
import zlib
from datetime import date, datetime
from xml.etree import ElementTree as ET

BIDI_CONTROLS = "‎‏‪‫‬‭‮⁦⁧⁨⁩؜﻿​"
ARABIC_INDIC = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
ARABIC_INDIC.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("date", "txn date", "transaction date", "value date", "booking date", "posting date", "التاريخ", "تاريخ", "تاريخ العملية", "تاريخ القيد"),
    "description": ("description", "details", "narration", "narrative", "particulars", "memo", "remarks", "البيان", "الوصف", "التفاصيل", "تفاصيل", "البيانات"),
    "amount": ("amount", "amount (aed)", "amount aed", "net amount", "المبلغ", "القيمة"),
    "debit": ("debit", "withdrawal", "withdrawals", "dr", "مدين", "سحب"),
    "credit": ("credit", "deposit", "deposits", "cr", "دائن", "إيداع", "ايداع"),
    "balance": ("balance", "running balance", "closing balance", "الرصيد", "رصيد"),
    "currency": ("currency", "ccy", "cur", "العملة", "عملة"),
    "counterparty": ("counterparty", "beneficiary", "payee", "payer", "party", "الطرف المقابل", "المستفيد", "الطرف الآخر"),
    "reference": ("reference", "ref", "bank reference", "transaction id", "txn id", "cheque no", "المرجع", "رقم المرجع", "رقم العملية"),
}
REQUIRED_HEADERS = ("date", "description")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%d/%m/%y", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y")
ARABIC_RE = re.compile(r"[؀-ۿ]")
LATIN_RE = re.compile(r"[A-Za-z]")


class ParseError(Exception):
    def __init__(self, cause: str, message: str = ""):
        super().__init__(message or cause)
        self.cause = cause


# --- text normalisation ----------------------------------------------------------------------------------


def normalise_text(value: str | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = "".join(ch for ch in text if ch not in BIDI_CONTROLS)
    text = text.translate(ARABIC_INDIC)
    return re.sub(r"\s+", " ", text).strip()


def clean_original(value: str | None) -> str:
    """Original text kept, but NFC-normalised and without invisible bidi controls (they never carry meaning)."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    return "".join(ch for ch in text if ch not in BIDI_CONTROLS).strip()


def language_class(text: str) -> str:
    has_ar = bool(ARABIC_RE.search(text))
    has_la = bool(LATIN_RE.search(text))
    if has_ar and has_la:
        return "mixed"
    if has_ar:
        return "arabic"
    if has_la:
        return "latin"
    return "none"


def detect_encoding(data: bytes) -> tuple[str, str]:
    """Returns (encoding label, decoded text). UTF-8 (with or without BOM) first, else Windows-1256."""
    try:
        return "UTF-8", data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "Windows-1256", data.decode("cp1256", errors="replace")


def parse_amount(value: str | None) -> int | None:
    """Amount string -> fils. Handles 1,234.56 / (1,234.56) / 1.234,56 / -1234 / Arabic-Indic digits."""
    if value is None:
        return None
    text = normalise_text(value).strip('"\'')
    if not text or text in ("-", "—", "–"):
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    text = text.replace("AED", "").replace("د.إ", "").replace(" ", "")
    if text.endswith("-"):
        negative, text = True, text[:-1]
    if text.startswith("-") or text.startswith("−"):
        negative, text = True, text[1:]
    if text.startswith("+"):
        text = text[1:]
    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")  # 1.234,56
    else:
        text = text.replace(",", "").replace("٬", "").replace("٫", ".")
    if not re.fullmatch(r"\d+(\.\d{1,4})?", text):
        return None
    whole, _, frac = text.partition(".")
    fils = int(whole) * 100 + int((frac + "00")[:2])
    return -fils if negative else fils


def parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date() if isinstance(value, datetime) else value
    text = normalise_text(value)
    if not text:
        return None
    text = text.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", text) else text
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # excel serial number
    if re.fullmatch(r"\d{5}(\.\d+)?", text):
        from datetime import timedelta

        return date(1899, 12, 30) + timedelta(days=int(float(text)))
    return None


def dedupe_key(account_ref: str | None, txn_date: date, amount_fils: int, currency: str, description_normalised: str, occurrence_index: int) -> str:
    raw = "|".join([account_ref or "", txn_date.isoformat(), str(amount_fils), currency.upper(), description_normalised.lower(), str(occurrence_index)])
    return hashlib.sha256(raw.encode()).hexdigest()


# --- readers --------------------------------------------------------------------------------------------


def read_table(file_type: str, data: bytes) -> tuple[list[list[str]], str | None]:
    """Returns (rows including the header row, encoding label)."""
    if file_type == "csv":
        encoding, text = detect_encoding(data)
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [[(c or "") for c in row] for row in csv.reader(io.StringIO(text), dialect)]
        return [r for r in rows if any(c.strip() for c in r)], encoding
    if file_type == "xlsx":
        return read_xlsx(data), "UTF-8"
    if file_type == "pdf":
        return read_text_pdf(data), "UTF-8"
    raise ParseError("wrong_type", "file type not accepted")


def read_xlsx(data: bytes) -> list[list[str]]:
    """Minimal XLSX reader: first worksheet, shared strings and inline strings, no formulas evaluated."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError("unreadable", "not a valid XLSX file") from exc
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    sheet_names = sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheet_names:
        raise ParseError("unreadable", "no worksheet found")
    root = ET.fromstring(zf.read(sheet_names[0]))
    rows: list[list[str]] = []
    for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", ns):
            ref = c.get("r", "A")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
                col = col * 26 + (ord(ch) - 64)
            t = c.get("t")
            v = c.find("m:v", ns)
            if t == "s" and v is not None and v.text is not None:
                value = shared[int(v.text)] if int(v.text) < len(shared) else ""
            elif t == "inlineStr":
                value = "".join(x.text or "" for x in c.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
            else:
                value = v.text if v is not None and v.text is not None else ""
            cells[col - 1] = value
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return [r for r in rows if any(str(c).strip() for c in r)]


def read_text_pdf(data: bytes) -> list[list[str]]:
    """Text-based PDF only: extracts text operands from content streams; image-only or encrypted PDFs are refused.
    Each text line is split on two or more spaces / tabs / pipes into columns."""
    if not data.startswith(b"%PDF"):
        raise ParseError("unreadable", "not a PDF file")
    if b"/Encrypt" in data:
        raise ParseError("password_protected", "encrypted PDF")
    texts: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        chunk = m.group(1)
        try:
            chunk = zlib.decompress(chunk)
        except zlib.error:
            pass
        for line in chunk.splitlines():
            parts = re.findall(rb"\((.*?)(?<!\\)\)\s*Tj|\[(.*?)\]\s*TJ", line)
            for a, b in parts:
                if a:
                    texts.append(a.decode("latin-1", errors="replace"))
                elif b:
                    texts.append("".join(x.decode("latin-1", errors="replace") for x in re.findall(rb"\((.*?)(?<!\\)\)", b)))
    if not texts:
        raise ParseError("image_only", "no text found in PDF")
    rows = [re.split(r"\s{2,}|\t|\|", t.strip()) for t in texts if t.strip()]
    return rows


# --- header mapping and row parsing --------------------------------------------------------------------


def map_headers(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(header):
        name = normalise_text(raw).lower().strip(" :")
        for field, names in HEADER_SYNONYMS.items():
            if field in mapping:
                continue
            if name in names or any(name.startswith(n) for n in names if len(n) > 3):
                mapping[field] = idx
                break
    missing = [h for h in REQUIRED_HEADERS if h not in mapping]
    if "amount" not in mapping and "debit" not in mapping and "credit" not in mapping:
        missing.append("amount or debit/credit")
    if missing:
        raise ParseError("unknown_header", f"unknown header; missing {missing or ['amount or debit/credit']}")
    return mapping


def parse_rows(rows: list[list[str]], *, account_ref: str | None, default_currency: str = "AED") -> tuple[list[dict], list[dict]]:
    """Returns (accepted, rejected). Each accepted row: txn_date, description, description_normalised, amount_fils,
    currency, counterparty, balance_fils, bank_reference, language_class, dedupe_key, occurrence_index, line_no."""
    if not rows:
        raise ParseError("unknown_header", "empty file")
    mapping = map_headers(rows[0])
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: dict[str, int] = {}

    def cell(row: list[str], field: str) -> str | None:
        i = mapping.get(field)
        return row[i] if i is not None and i < len(row) else None

    for n, row in enumerate(rows[1:], start=2):
        txn_date = parse_date(cell(row, "date"))
        if txn_date is None:
            rejected.append({"line_no": n, "reason": "date_invalid"})
            continue
        amount = parse_amount(cell(row, "amount")) if "amount" in mapping else None
        if amount is None and ("debit" in mapping or "credit" in mapping):
            debit = parse_amount(cell(row, "debit")) or 0
            credit = parse_amount(cell(row, "credit")) or 0
            if debit == 0 and credit == 0 and not (cell(row, "debit") or cell(row, "credit")):
                amount = None
            else:
                amount = credit - abs(debit)
        if amount is None:
            rejected.append({"line_no": n, "reason": "amount_invalid"})
            continue
        description = clean_original(cell(row, "description"))
        if not description:
            rejected.append({"line_no": n, "reason": "description_missing"})
            continue
        currency = (normalise_text(cell(row, "currency")) or default_currency).upper()[:3]
        if not re.fullmatch(r"[A-Z]{3}", currency):
            rejected.append({"line_no": n, "reason": "currency_invalid"})
            continue
        desc_norm = normalise_text(description)
        base = "|".join([account_ref or "", txn_date.isoformat(), str(amount), currency, desc_norm.lower()])
        occurrence = seen.get(base, 0)
        seen[base] = occurrence + 1
        accepted.append(
            {
                "line_no": n,
                "txn_date": txn_date,
                "description": description,
                "description_normalised": desc_norm,
                "amount_fils": amount,
                "currency": currency,
                "counterparty": clean_original(cell(row, "counterparty")) or None,
                "balance_fils": parse_amount(cell(row, "balance")),
                "bank_reference": normalise_text(cell(row, "reference")) or None,
                "language_class": language_class(description),
                "occurrence_index": occurrence,
                "dedupe_key": dedupe_key(account_ref, txn_date, amount, currency, desc_norm, occurrence),
            }
        )
    return accepted, rejected


def scan_for_malware(data: bytes) -> str:
    """Scanner stub: flags the EICAR test string; real scanning is a UAE-hosted service in production."""
    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data:
        return "infected"
    return "clean_stub"
