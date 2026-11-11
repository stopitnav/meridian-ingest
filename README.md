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
a per-row outcome (`inserted` / `unchanged` / `corrected` / `rejected` /
`held` / `superseded_duplicate`) and every issue found, with original
and corrected values. `sample-validation-report.json` in this repo is
the report produced from the provided sample feed.

## 2. Design decisions

1. **Reject/warn/auto-fix per field**, not per row: missing
   `source_row_id`, `status=Closed` with nonzero NAV, and negative
   NAV/commitment are **rejected** — each either breaks the audit-trail
   key or is a stated client-side bug, so ingesting it means trusting
   bad data. Whitespace, date-format variants, and the share-class
   suffix are **auto-fixed silently** — low-risk and mechanical. Blank
   commitment is **auto-fixed to 0 + warned**, per Dana's instruction.
   Blank currency is **held**, not auto-fixed — defaulting a money
   field's denomination is riskier than defaulting a non-monetary one.
2. **"Held" ≠ "rejected"**: rejected means the data is wrong; held means
   we lack enough information to ingest it safely yet. Keeping them
   distinct keeps the client report honest about bug vs. open question.
3. **Idempotency is content-hash based, not just key-based.** Keyed by
   `source_row_id` (audit-trail requirement), but canonical fields are
   also hashed: an exact resend no-ops, a corrected re-delivery updates
   with a recorded field-level diff — "latest file wins" without
   silently clobbering history.
4. **In-file duplicates are handled separately from cross-file
   re-delivery.** `src-1007` appears twice in one file with different
   NAVs — last occurrence wins, but it's flagged rather than resolved
   silently, since this case wasn't one Dana's notes described.
5. **Validation is row-level, not file-level** — a bad row doesn't
   block the rest of the file. At 100k rows, an all-or-nothing file
   gate would block good data for no benefit and break "safe to re-run."
6. **Core logic (`core/`) is framework-agnostic** — no CLI/HTTP
   coupling, so `cli.py` and `api.py` share it with no duplication.
7. **Share-class split is pattern-specific** (`<Fund> - Class <X>`),
   not a generic dash-split, so an unrelated dash in a fund name
   wouldn't get corrupted at scale.
8. **Non-USD currency is accepted, not rejected** — EUR is valid ISO
   4217, just the uncommon case; flagged for FX review, not an error.
9. **SQLite over in-memory** — the brief asks for safe re-run behavior,
   which is only credibly demonstrable against a store that persists
   between runs.
10. **What I'd change at 100k-row / 40-fund scale** (discussion only,
    not built, per the brief): stream the CSV instead of loading it
    fully into memory; track ingestion at the file level
    (filename/checksum/timestamp) to catch out-of-order delivery, not
    just row-level conflicts; move the per-file summary from email to
    the webhook Dana mentioned; add schema-drift detection before
    row-level validation starts, since that's a cheaper, earlier
    failure mode at that volume.
