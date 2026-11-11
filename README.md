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

1. **Reject/warn/auto-fix per field**, not per row — and only two row
   outcomes exist, accepted or rejected; there's no third "maybe" state.
   Missing `source_row_id`, `status=Closed` with nonzero NAV, negative
   NAV/commitment, and blank currency are all **rejected**. They differ
   in *why* — the first three are confirmed bugs ingesting them would
   mean trusting bad data, while blank currency is just missing
   information we won't guess at (defaulting a money field's
   denomination is riskier than defaulting a non-monetary one) — but
   that distinction lives in each issue's message, not in a separate
   outcome, since the system treats them identically either way.
   Whitespace, date-format variants, and the share-class suffix are
   **auto-fixed silently**. Blank commitment is **auto-fixed to 0 +
   warned**, per Dana's instruction.

   | | Row stored? | Issue severity |
   |---|---|---|
   | Auto-fix (silent) | ✅ accepted | `info` |
   | Auto-fix (flagged) / warn | ✅ accepted | `warn` |
   | Reject (confirmed bug or missing info) | ❌ rejected | `reject` |

2. **Idempotency is content-hash based, not just key-based.** Keyed by
   `source_row_id` (audit-trail requirement), but canonical fields are
   also hashed: an exact resend is **ignored** (no-op), a corrected
   re-delivery is **updated** with a recorded field-level diff —
   "latest file wins" without silently clobbering history.
3. **In-file duplicates are handled separately from cross-file
   re-delivery, and both outcomes are `ignored` for a different
   reason.** `src-1007` appears twice in one file with different NAVs —
   last occurrence wins, the earlier one is `ignored`, but it's flagged
   via its issue message rather than resolved silently, since this case
   wasn't one Dana's notes described. (An exact-resend no-op and a
   superseded in-file duplicate both land on `ignored` — the *why* lives
   in the issue message, not in a separate outcome bucket, same
   reasoning as the reject/held collapse above.)
4. **Validation is row-level, not file-level** — a bad row doesn't
   block the rest of the file. At 100k rows, an all-or-nothing file
   gate would block good data for no benefit and break "safe to re-run."
5. **Core logic (`core/`) is framework-agnostic** — no CLI/HTTP
   coupling, so `cli.py` and `api.py` share it with no duplication.
6. **Share-class split is pattern-specific** (`<Fund> - Class <X>`),
   not a generic dash-split, so an unrelated dash in a fund name
   wouldn't get corrupted at scale.
7. **Non-USD currency is accepted, not rejected** — EUR is valid ISO
   4217, just the uncommon case; flagged for FX review, not an error.
8. **SQLite over in-memory** — the brief asks for safe re-run behavior,
   which is only credibly demonstrable against a store that persists
   between runs.
9. **What I'd change at 100k-row / 40-fund scale** (discussion only,
   not built, per the brief): stream the CSV instead of loading it
   fully into memory; track ingestion at the file level
   (filename/checksum/timestamp) to catch out-of-order delivery, not
   just row-level conflicts; move the per-file summary from email to
   the webhook Dana mentioned; add schema-drift detection before
   row-level validation starts, since that's a cheaper, earlier
   failure mode at that volume.

   One thing worth calling out specifically: the content-hash idempotency
   check (decision #2) is **not** where the cost would be at 100k rows —
   measured at ~0.4s for 100k hash computations, negligible. The actual
   bottleneck is that `PositionStore` commits after every single row
   (`_insert`/`_touch`/`_update` each call `conn.commit()`); measured at
   ~35s for 100k rows that way, vs. ~0.8s batched into one commit per
   file. That's a ~40x difference from changing *when* we commit, not
   from anything related to hashing — worth fixing before this scales,
   but deliberately left as a known, measured gap rather than fixed here.
