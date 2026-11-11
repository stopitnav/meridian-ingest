# Meridian Positions Feed — Ingestion & Validation

## How to run

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

Output: `positions.sqlite3` (canonical store) and a JSON report with a
per-row outcome (`inserted` / `unchanged` / `corrected` / `rejected` /
`held` / `superseded_duplicate`) and every issue found, with original and
corrected values.

`sample-validation-report.json` in this repo is the report produced from
the provided sample feed.

## Design decisions

1. **Reject vs. warn vs. auto-fix** was decided per-field against what the
   client could/couldn't reasonably defend: missing `source_row_id`,
   `status=Closed` with nonzero NAV, and negative NAV/commitment are
   **rejected** (either breaks the audit-trail key or is a stated bug on
   their side — ingesting it would mean trusting bad data). Whitespace,
   date-format variants, and the share-class suffix are **auto-fixed
   silently** (low-risk, mechanical, and Dana explicitly said normalizing
   dates is fine). Blank/non-numeric commitment is **auto-fixed to 0 +
   warned**, per Dana's explicit instruction. Blank currency is **held**
   (not auto-fixed) — defaulting a money field's currency felt riskier
   than defaulting a non-monetary field, so I didn't guess.
2. **"Held" is a separate outcome from "rejected"** — rejected means we've
   determined the data is wrong; held means we don't have enough
   information to safely ingest it yet. Keeping them distinct makes the
   client-facing report more honest about what's a bug vs. what's an open
   question.
3. **Idempotency is content-hash based, not just key-based.** Each
   position is keyed by `source_row_id` (per Dana's audit-trail
   requirement), but we also hash the canonical fields. An exact resend
   hashes identically and no-ops; a corrected re-delivery (same key,
   different values) is detected and applied as an update, with a
   field-level diff recorded — "latest file wins" without silently
   clobbering history.
4. **In-file duplicates are a different problem from cross-file
   re-delivery** and are handled separately: if the same `source_row_id`
   appears twice in one file (as `src-1007` does in the sample), the last
   occurrence wins, but it's flagged as a warning rather than resolved
   silently — this wasn't a case Dana's notes described, so it's
   surfaced for her to confirm rather than assumed.
5. **Validation is row-level, not file-level**: a bad row doesn't block
   the rest of the file from being ingested. At 100k rows, failing an
   entire file over a handful of bad rows would block a lot of good data
   for no benefit, and makes "safe to re-run" meaningless.
6. **Core logic is framework-agnostic** (`core/`): parsing, validation,
   and storage have no CLI or HTTP coupling, so the same logic backs both
   `cli.py` and `api.py` with no duplication.
7. **Fund name / share class split is pattern-specific, not a generic
   dash-split** — matches on `<Fund> - Class <X>` specifically so a fund
   name with an unrelated dash wouldn't get corrupted at scale.
8. **Non-USD currency is accepted, not rejected** — EUR is a valid ISO
   4217 currency, just not the common case ("almost always USD" implies
   it's not "always"). It's flagged for FX/multi-currency review rather
   than treated as an error.
9. **SQLite over in-memory**: the brief explicitly asks for safe re-run
   behavior, which is easiest to demonstrate credibly against a real
   persisted store rather than an in-memory one that resets between runs.
10. **What I'd change at 100k-row / 40-fund scale** (not built, by design,
    per the brief): stream the CSV instead of loading fully into memory;
    track ingestion runs at the file level (filename/checksum/timestamp)
    so we can detect out-of-order file delivery, not just row-level
    conflicts; move the per-file summary from email to the webhook Dana
    mentioned; add schema-drift detection (new/missing columns) before
    row-level validation even starts, since that's a cheaper, earlier
    failure mode at that volume.
