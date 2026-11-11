from decimal import Decimal

from .models import CanonicalPosition, Issue, RowResult
from .parse import parse_date, parse_decimal, parse_int, split_fund_name

VALID_STATUSES = {"active", "closed"}


def validate_row(row_number: int, raw: dict) -> RowResult:
    """Validate and normalize a single CSV row into a CanonicalPosition.

    Returns a RowResult with outcome set to "accepted", "rejected", or
    "held" (valid-looking data we don't have enough information to
    safely ingest, as opposed to data we've determined is wrong).
    Intra-file duplicate resolution happens in a second pass (see
    resolve_duplicates), so outcome may be downgraded afterwards.
    """
    issues: list[Issue] = []
    reject = False
    hold = False

    source_row_id = (raw.get("source_row_id") or "").strip() or None
    if source_row_id is None:
        issues.append(Issue(
            field="source_row_id", code="missing_key", severity="reject",
            message="Row has no source_row_id; cannot key it for the audit trail.",
            original_value=raw.get("source_row_id"),
        ))
        reject = True

    account_id = (raw.get("account_id") or "").strip() or None
    if account_id is None:
        issues.append(Issue(
            field="account_id", code="missing_field", severity="reject",
            message="Row has no account_id; required for advisor coverage scoping.",
        ))
        reject = True

    account_holder = (raw.get("account_holder") or "").strip() or None

    fund_name_raw = raw.get("fund_name") or ""
    fund_name, share_class = split_fund_name(fund_name_raw)
    if fund_name_raw.strip() != fund_name_raw:
        issues.append(Issue(
            field="fund_name", code="whitespace_trimmed", severity="info",
            message="Trimmed leading/trailing whitespace from fund_name.",
            original_value=fund_name_raw, corrected_value=fund_name,
        ))
    if share_class:
        issues.append(Issue(
            field="fund_name", code="share_class_split", severity="info",
            message="Split appended share class into its own field.",
            original_value=fund_name_raw, corrected_value=f"{fund_name} | {share_class}",
        ))

    vintage_year = parse_int(raw.get("vintage_year") or "")
    if vintage_year is None and (raw.get("vintage_year") or "").strip():
        issues.append(Issue(
            field="vintage_year", code="unparseable", severity="warn",
            message="vintage_year is not a valid integer.",
            original_value=raw.get("vintage_year"),
        ))

    commitment_raw = raw.get("commitment") or ""
    commitment = parse_decimal(commitment_raw)
    if commitment is None:
        issues.append(Issue(
            field="commitment", code="blank_or_non_numeric", severity="warn",
            message="Commitment is blank/non-numeric; treated as 0 (commitment-free secondary purchase). Please fix at source.",
            original_value=commitment_raw, corrected_value="0",
        ))
        commitment = Decimal("0")
    elif commitment < 0:
        issues.append(Issue(
            field="commitment", code="negative", severity="reject",
            message="Commitment is negative, which should never happen.",
            original_value=commitment_raw,
        ))
        reject = True

    nav_raw = raw.get("nav") or ""
    nav = parse_decimal(nav_raw)
    if nav is None:
        issues.append(Issue(
            field="nav", code="unparseable", severity="reject",
            message="NAV is blank/non-numeric.",
            original_value=nav_raw,
        ))
        reject = True
    elif nav < 0:
        issues.append(Issue(
            field="nav", code="negative", severity="reject",
            message="NAV is negative; not a valid position value.",
            original_value=nav_raw,
        ))
        reject = True

    nav_date_raw = raw.get("nav_date") or ""
    nav_date = parse_date(nav_date_raw)
    if nav_date is None:
        issues.append(Issue(
            field="nav_date", code="unparseable", severity="reject",
            message="nav_date doesn't match any known format (ISO, MM/DD/YYYY, DD-Mon-YYYY).",
            original_value=nav_date_raw,
        ))
        reject = True
    elif nav_date != nav_date_raw.strip():
        issues.append(Issue(
            field="nav_date", code="format_normalized", severity="info",
            message="Normalized nav_date to ISO format.",
            original_value=nav_date_raw, corrected_value=nav_date,
        ))

    currency_raw = (raw.get("currency") or "").strip()
    if not currency_raw:
        issues.append(Issue(
            field="currency", code="missing", severity="hold",
            message="Currency is blank. Holding rather than assuming USD on a money field.",
        ))
        hold = True
        currency = None
    else:
        currency = currency_raw.upper()
        if currency != currency_raw:
            issues.append(Issue(
                field="currency", code="case_normalized", severity="warn",
                message="Normalized currency code to uppercase.",
                original_value=currency_raw, corrected_value=currency,
            ))
        if currency != "USD":
            issues.append(Issue(
                field="currency", code="non_usd", severity="warn",
                message=f"Non-USD currency ({currency}); flagged for multi-currency/FX review.",
            ))

    status_raw = (raw.get("status") or "").strip()
    status = status_raw.capitalize() if status_raw else None
    if status_raw.lower() not in VALID_STATUSES:
        issues.append(Issue(
            field="status", code="invalid_value", severity="reject",
            message=f"status must be Active or Closed, got '{status_raw}'.",
            original_value=status_raw,
        ))
        reject = True
    elif status_raw.lower() == "closed" and nav is not None and nav != 0:
        issues.append(Issue(
            field="status", code="closed_with_nonzero_nav", severity="reject",
            message="Closed position has nonzero NAV; per client this indicates a bug on their side. Flagging rather than ingesting.",
            original_value=str(nav),
        ))
        reject = True

    advisor_email = (raw.get("advisor_email") or "").strip() or None
    if not advisor_email or "@" not in advisor_email:
        issues.append(Issue(
            field="advisor_email", code="missing_or_invalid", severity="warn",
            message="advisor_email is missing or not a valid email; notifications may not be deliverable.",
            original_value=advisor_email,
        ))

    if reject:
        outcome = "rejected"
        position = None
    elif hold:
        outcome = "held"
        position = None
    else:
        outcome = "accepted"
        position = CanonicalPosition(
            source_row_id=source_row_id,
            account_id=account_id,
            account_holder=account_holder,
            fund_name=fund_name,
            share_class=share_class,
            vintage_year=vintage_year,
            commitment=commitment,
            nav=nav,
            nav_date=nav_date,
            currency=currency,
            status=status,
            advisor_email=advisor_email,
            raw=raw,
        )

    return RowResult(
        row_number=row_number,
        source_row_id=source_row_id,
        outcome=outcome,
        position=position,
        issues=issues,
    )


def resolve_duplicates(results: list[RowResult]) -> list[RowResult]:
    """Resolve source_row_id values that appear more than once within a
    single file. Last occurrence (by row order) wins; earlier ones are
    superseded and flagged rather than silently dropped.
    """
    by_id: dict[str, list[RowResult]] = {}
    for r in results:
        if r.source_row_id:
            by_id.setdefault(r.source_row_id, []).append(r)

    for source_row_id, group in by_id.items():
        if len(group) <= 1:
            continue
        winner = group[-1]
        losers = group[:-1]
        other_rows = ", ".join(f"row {r.row_number}" for r in losers)
        winner.issues.append(Issue(
            field="source_row_id", code="duplicate_in_file", severity="warn",
            message=(
                f"source_row_id '{source_row_id}' appeared {len(group)} times in this file "
                f"(also {other_rows}); last occurrence in file order was used. "
                "Please confirm whether in-file duplicates are expected."
            ),
        ))
        for loser in losers:
            loser.outcome = "superseded_duplicate"
            loser.position = None
            loser.issues.append(Issue(
                field="source_row_id", code="duplicate_in_file", severity="warn",
                message=f"Superseded by row {winner.row_number} for the same source_row_id within this file.",
            ))

    return results
