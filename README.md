# Meridian Positions Feed — Ingestion & Validation

## 1. How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # only needed for the API; the CLI has no dependencies

# CLI
python cli.py ingest sample-positions-feed.csv --report report.json

# Re-run — safe, won't duplicate or re-insert unchanged rows
python cli.py ingest sample-positions-feed.csv --report report.json

# Minimal API (optional)
uvicorn api:app --reload
curl -X POST http://127.0.0.1:8000/ingest -F "file=@sample-positions-feed.csv"
curl http://127.0.0.1:8000/positions
```

**Output:** `positions.sqlite3` (canonical store) and a JSON report with
a per-row outcome (`inserted` / `updated` / `ignored` / `rejected`) and
every issue found, with original and corrected values.
`sample-validation-report.json` in this repo is the report produced
from the provided sample feed.

## 2. Data model

**Canonical position** (`core/models.py::CanonicalPosition`) — what a
validated row becomes, decoupled from Meridian's raw column names:

| Field | Type | From CSV column | Notes |
|---|---|---|---|
| `source_row_id` | `str` | `source_row_id` | Primary key; audit-trail key back to Meridian's system |
| `account_id` | `str` | `account_id` | Internal account number, not the client's display name |
| `account_holder` | `str` | `account_holder` | Display only — never keyed off, per Dana's note |
| `fund_name` | `str` | `fund_name` | Share class suffix stripped out (see below) |
| `share_class` | `str \| None` | `fund_name` | Parsed out of `fund_name` when present (`<Fund> - Class <X>`) |
| `vintage_year` | `int \| None` | `vintage_year` | |
| `commitment` | `Decimal` | `commitment` | Blank/non-numeric → `0` (flagged, never silently dropped) |
| `nav` | `Decimal` | `nav` | |
| `nav_date` | `str` (ISO `yyyy-mm-dd`) | `nav_date` | Normalized from whatever format the legacy system emitted |
| `currency` | `str` | `currency` | Uppercased ISO 4217 |
| `status` | `str` | `status` | `Active` or `Closed` |
| `advisor_email` | `str \| None` | `advisor_email` | |
| `raw` | `dict` | *(whole row)* | Kept in memory for the report only — **never persisted** |

**SQLite table** (`core/store.py::SCHEMA`) mirrors the canonical fields
exactly, plus four audit columns the canonical model doesn't carry:
`content_hash` (drives the inserted/updated/ignored decision),
`first_ingested_at`, `last_ingested_at`, `last_source_file`. Two
deliberate choices in the schema:

- `commitment` and `nav` are stored as `TEXT` (stringified `Decimal`),
  not `REAL` — avoids float rounding on money fields, which matters
  more than query-side arithmetic convenience for a position store.
- `raw` is dropped before anything reaches SQLite. The original CSV
  row is only needed to build issue messages (original vs. corrected
  value) at report time; keeping it in the store would mean persisting
  Meridian's raw export shape indefinitely for no read path that uses it.

**Report-only types** (`Issue`, `RowResult`) never touch the database —
they exist purely to build the JSON/console report and are discarded
after a run.

## 3. Design decisions

1. **Reject/warn/auto-fix is decided per field.** Confirmed bugs (missing
   `source_row_id`, `status=Closed` with nonzero NAV, negative NAV/
   commitment) and missing-required-info (blank currency) are
   **rejected**. Mechanical, low-risk fixes (whitespace, date formats,
   share-class split) are **auto-fixed silently**. Blank commitment is
   **auto-fixed to 0 + warned**, per Dana's instruction. Only two row
   outcomes exist — accepted or rejected; *why* lives in the issue
   message, not in extra outcome states.
2. **Idempotent via content-hash, not just key.** Exact resend →
   `ignored`; same key, changed values → `updated` with a field diff;
   new key → `inserted`. "Latest file wins" without silently clobbering
   history.
3. **In-file duplicates (`src-1007`) are `ignored` too**, same bucket as
   a resend — last occurrence wins, but flagged in the issue message
   rather than resolved silently.
4. **Validation is row-level, not file-level** — one bad row doesn't
   block the rest of the file.
5. **Non-USD currency is accepted, not rejected** — EUR is valid, just
   uncommon; flagged for FX review rather than treated as an error.
6. **Share-class parsing is pattern-specific** (`<Fund> - Class <X>`),
   not a generic dash-split, so an unrelated dash won't corrupt a name.
7. **At 100k-row scale** (discussion only, not built): stream the CSV
   instead of loading it fully into memory; batch SQLite commits once
   per file instead of once per row — measured ~35s → ~0.8s for 100k
   rows, while the content-hash check itself is only ~0.4s and not the
   bottleneck; track ingestion at the file level to catch out-of-order
   delivery; move the summary from email to a webhook.
