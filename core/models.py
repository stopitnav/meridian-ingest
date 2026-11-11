from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class Issue:
    field: str
    code: str
    severity: str  # "reject" | "warn" | "info"
    message: str
    original_value: Optional[str] = None
    corrected_value: Optional[str] = None


@dataclass
class CanonicalPosition:
    source_row_id: Optional[str]
    account_id: Optional[str]
    account_holder: Optional[str]
    fund_name: Optional[str]
    share_class: Optional[str]
    vintage_year: Optional[int]
    commitment: Optional[Decimal]
    nav: Optional[Decimal]
    nav_date: Optional[str]  # ISO yyyy-mm-dd
    currency: Optional[str]
    status: Optional[str]
    advisor_email: Optional[str]
    raw: dict = field(default_factory=dict)


@dataclass
class RowResult:
    row_number: int  # 1-indexed within the file, header excluded
    source_row_id: Optional[str]
    # "accepted" | "rejected" from validate_row; "accepted" is then
    # replaced with "inserted" | "updated" | "ignored" once stored, and
    # resolve_duplicates may replace any outcome with "ignored" for a
    # losing in-file duplicate (see its Issue for why it was ignored).
    outcome: str
    position: Optional[CanonicalPosition]
    issues: list[Issue] = field(default_factory=list)
