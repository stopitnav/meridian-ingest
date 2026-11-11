import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

SHARE_CLASS_RE = re.compile(r"^(?P<fund>.+?)\s*-\s*Class\s+(?P<share_class>[A-Za-z0-9]+)\s*$")

# Date formats we've observed in the feed, tried in order.
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"]


def split_fund_name(raw: str) -> tuple[str, Optional[str]]:
    """Split 'Fund Name - Class A' into ('Fund Name', 'A'). Trims whitespace.
    Only splits on the specific '- Class <X>' suffix pattern, not any dash,
    so a fund name that happens to contain an unrelated dash is left alone.
    """
    trimmed = raw.strip()
    match = SHARE_CLASS_RE.match(trimmed)
    if match:
        return match.group("fund").strip(), match.group("share_class").strip()
    return trimmed, None


def parse_date(raw: str) -> Optional[str]:
    """Normalize a date string to ISO yyyy-mm-dd. Returns None if unparseable."""
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_decimal(raw: str) -> Optional[Decimal]:
    """Parse a numeric field. Returns None if blank or non-numeric."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_int(raw: str) -> Optional[int]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
