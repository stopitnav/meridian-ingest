#!/usr/bin/env python3
import argparse
import json
import os
import sys

from core.pipeline import run_ingestion

DEFAULT_DB = "positions.sqlite3"


def main():
    parser = argparse.ArgumentParser(description="Meridian positions feed ingestion")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest a CSV feed file")
    ingest.add_argument("csv_path", help="Path to the positions CSV file")
    ingest.add_argument("--db", default=DEFAULT_DB, help=f"SQLite db path (default: {DEFAULT_DB})")
    ingest.add_argument("--report", default="report.json", help="Where to write the JSON report")

    args = parser.parse_args()

    if args.command == "ingest":
        with open(args.csv_path, "r", newline="") as f:
            csv_text = f.read()
        report = run_ingestion(csv_text, source_name=os.path.basename(args.csv_path), db_path=args.db)

        with open(args.report, "w") as f:
            json.dump(report, f, indent=2, default=str)

        s = report["summary"]
        print(f"Ingested {args.csv_path} -> {args.db}")
        print(f"Total rows: {s['total_rows']}")
        print(f"  inserted: {s['inserted']}")
        print(f"  updated:  {s['updated']}")
        print(f"  ignored:  {s['ignored']}")
        print(f"  rejected: {s['rejected']}")
        print(f"Full report: {args.report}")


if __name__ == "__main__":
    sys.exit(main())
