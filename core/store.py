import hashlib
import json
import sqlite3
from dataclasses import asdict
from decimal import Decimal

from .models import CanonicalPosition

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    source_row_id TEXT PRIMARY KEY,
    account_id TEXT,
    account_holder TEXT,
    fund_name TEXT,
    share_class TEXT,
    vintage_year INTEGER,
    commitment TEXT,
    nav TEXT,
    nav_date TEXT,
    currency TEXT,
    status TEXT,
    advisor_email TEXT,
    content_hash TEXT NOT NULL,
    first_ingested_at TEXT NOT NULL,
    last_ingested_at TEXT NOT NULL,
    last_source_file TEXT
);
"""


def _content_hash(p: CanonicalPosition) -> str:
    """Hash of the fields that matter for detecting a real change vs. an
    exact resend. Excludes ingestion metadata and the raw row on purpose.
    """
    payload = {
        "account_id": p.account_id,
        "account_holder": p.account_holder,
        "fund_name": p.fund_name,
        "share_class": p.share_class,
        "vintage_year": p.vintage_year,
        "commitment": str(p.commitment),
        "nav": str(p.nav),
        "nav_date": p.nav_date,
        "currency": p.currency,
        "status": p.status,
        "advisor_email": p.advisor_email,
    }
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


class PositionStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert(self, position: CanonicalPosition, source_file: str, now: str) -> tuple[str, dict | None]:
        """Insert, update, or no-op a position. Returns (outcome, diff)
        where outcome is "inserted", "unchanged", or "corrected", and
        diff is a field-level dict of changes for "corrected" (else None).
        """
        new_hash = _content_hash(position)
        cur = self.conn.execute(
            "SELECT content_hash, account_id, account_holder, fund_name, share_class, "
            "vintage_year, commitment, nav, nav_date, currency, status, advisor_email, first_ingested_at "
            "FROM positions WHERE source_row_id = ?",
            (position.source_row_id,),
        )
        existing = cur.fetchone()

        if existing is None:
            self.conn.execute(
                "INSERT INTO positions (source_row_id, account_id, account_holder, fund_name, "
                "share_class, vintage_year, commitment, nav, nav_date, currency, status, "
                "advisor_email, content_hash, first_ingested_at, last_ingested_at, last_source_file) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    position.source_row_id, position.account_id, position.account_holder,
                    position.fund_name, position.share_class, position.vintage_year,
                    str(position.commitment), str(position.nav), position.nav_date,
                    position.currency, position.status, position.advisor_email,
                    new_hash, now, now, source_file,
                ),
            )
            self.conn.commit()
            return "inserted", None

        old_hash = existing[0]
        if old_hash == new_hash:
            self.conn.execute(
                "UPDATE positions SET last_ingested_at = ?, last_source_file = ? WHERE source_row_id = ?",
                (now, source_file, position.source_row_id),
            )
            self.conn.commit()
            return "unchanged", None

        old_fields = dict(zip(
            ["account_id", "account_holder", "fund_name", "share_class", "vintage_year",
             "commitment", "nav", "nav_date", "currency", "status", "advisor_email"],
            existing[1:12],
        ))
        new_fields = {
            "account_id": position.account_id, "account_holder": position.account_holder,
            "fund_name": position.fund_name, "share_class": position.share_class,
            "vintage_year": position.vintage_year, "commitment": str(position.commitment),
            "nav": str(position.nav), "nav_date": position.nav_date,
            "currency": position.currency, "status": position.status,
            "advisor_email": position.advisor_email,
        }
        diff = {
            k: {"old": old_fields[k], "new": new_fields[k]}
            for k in old_fields
            if str(old_fields[k]) != str(new_fields[k])
        }

        self.conn.execute(
            "UPDATE positions SET account_id=?, account_holder=?, fund_name=?, share_class=?, "
            "vintage_year=?, commitment=?, nav=?, nav_date=?, currency=?, status=?, advisor_email=?, "
            "content_hash=?, last_ingested_at=?, last_source_file=? WHERE source_row_id=?",
            (
                position.account_id, position.account_holder, position.fund_name, position.share_class,
                position.vintage_year, str(position.commitment), str(position.nav), position.nav_date,
                position.currency, position.status, position.advisor_email,
                new_hash, now, source_file, position.source_row_id,
            ),
        )
        self.conn.commit()
        return "corrected", diff

    def all_positions(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT source_row_id, account_id, account_holder, fund_name, share_class, "
            "vintage_year, commitment, nav, nav_date, currency, status, advisor_email, "
            "first_ingested_at, last_ingested_at, last_source_file FROM positions"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
