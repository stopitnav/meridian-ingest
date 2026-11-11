import csv
import io
from dataclasses import asdict
from datetime import datetime, timezone

from .store import PositionStore
from .validate import resolve_duplicates, validate_row


def run_ingestion(csv_text: str, source_file: str, db_path: str) -> dict:
    """Run the full ingest pipeline over CSV text and return a JSON-able
    report. Safe to call repeatedly with the same file: already-stored,
    unchanged rows are reported as "unchanged", not re-inserted.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    results = [validate_row(i + 1, row) for i, row in enumerate(reader)]
    results = resolve_duplicates(results)

    now = datetime.now(timezone.utc).isoformat()
    store = PositionStore(db_path)
    try:
        for r in results:
            if r.outcome == "accepted" and r.position is not None:
                store_outcome, diff = store.upsert(r.position, source_file, now)
                r.outcome = store_outcome
                if diff:
                    r.issues_diff = diff  # attached dynamically, only for "corrected"
    finally:
        store.close()

    summary = {"total_rows": len(results)}
    for outcome in ["inserted", "unchanged", "corrected", "rejected", "held", "superseded_duplicate"]:
        summary[outcome] = sum(1 for r in results if r.outcome == outcome)

    rows_report = []
    for r in results:
        entry = {
            "row_number": r.row_number,
            "source_row_id": r.source_row_id,
            "outcome": r.outcome,
            "issues": [
                {
                    "field": i.field, "code": i.code, "severity": i.severity,
                    "message": i.message, "original_value": i.original_value,
                    "corrected_value": i.corrected_value,
                }
                for i in r.issues
            ],
        }
        diff = getattr(r, "issues_diff", None)
        if diff:
            entry["diff"] = diff
        rows_report.append(entry)

    return {
        "source_file": source_file,
        "ingested_at": now,
        "summary": summary,
        "rows": rows_report,
    }
