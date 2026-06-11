"""Import spend entries from a CSV file into the v2 SQLite DB.

Expected CSV columns (in any order): Time, Amount, Card, Category, Remarks
  - Time:     "YYYY-MM-DD HH:MM:SS"
  - Amount:   numeric (e.g. 33.54)
  - Card:     card name (must exist in the cards table, or use --no-validate)
  - Category: category name
  - Remarks:  optional free text

Usage:
    python import_spend.py spend.csv [--db ./data/bot.db] [--no-validate] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import db


REQUIRED_COLS = {"Time", "Amount", "Card", "Category"}


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLS - set(reader.fieldnames or [])
        if missing:
            print(f"error: CSV is missing columns: {', '.join(sorted(missing))}", file=sys.stderr)
            sys.exit(1)
        return list(reader)


def parse_row(row: dict, line: int) -> tuple[datetime, Decimal, str, str, str | None] | None:
    try:
        ts = datetime.strptime(row["Time"].strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        print(f"  line {line}: skipping — bad timestamp {row['Time']!r}", file=sys.stderr)
        return None

    try:
        amount = Decimal(row["Amount"].strip())
    except InvalidOperation:
        print(f"  line {line}: skipping — bad amount {row['Amount']!r}", file=sys.stderr)
        return None

    card = row["Card"].strip()
    category = row["Category"].strip()
    remarks = row.get("Remarks", "").strip() or None

    if not card or not category:
        print(f"  line {line}: skipping — empty card or category", file=sys.stderr)
        return None

    return ts, amount, card, category, remarks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path, help="Path to the CSV file to import")
    parser.add_argument("--db", type=Path, default=Path("./data/bot.db"))
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip checking that card names exist in the DB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate without writing to the DB")
    args = parser.parse_args()

    if not args.csv_file.exists():
        print(f"error: file not found: {args.csv_file}", file=sys.stderr)
        return 1

    rows = load_csv(args.csv_file)
    db.init(args.db)

    if not args.no_validate:
        known_cards = {c.name for c in db.get_cards()}
        unknown = {r["Card"].strip() for r in rows if r["Card"].strip() not in known_cards}
        if unknown:
            print("error: card(s) not found in DB:", ", ".join(sorted(unknown)), file=sys.stderr)
            print("  Add them via /admin or re-run with --no-validate to skip this check.", file=sys.stderr)
            return 1

    imported = skipped = 0
    for i, row in enumerate(rows, start=2):  # line 1 = header
        parsed = parse_row(row, i)
        if parsed is None:
            skipped += 1
            continue
        ts, amount, card, category, remarks = parsed
        if not args.dry_run:
            db.append_spend(ts, amount, card, category, remarks)
        imported += 1

    label = "Would import" if args.dry_run else "Imported"
    print(f"{label} {imported} entries, skipped {skipped}.")
    if args.dry_run:
        print("(dry run — no changes written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
