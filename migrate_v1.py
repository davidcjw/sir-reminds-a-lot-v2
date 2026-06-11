"""One-off migration from sir-reminds-a-lot (v1) markdown files to the v2 SQLite DB.

Parses categories.md, creditcards.md and merchant_categories.md from the v1
repo and pre-populates the categories, cards and merchant_aliases tables.

Usage:
    python migrate_v1.py [--source ../sir-reminds-a-lot] [--db ./data/bot.db]

Safe to re-run: categories use INSERT OR IGNORE, cards and merchant aliases
use INSERT OR REPLACE.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import db


def parse_categories(path: Path) -> list[str]:
    categories = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        categories.append(line)
    return categories


def parse_cards(path: Path) -> list[tuple[str, str | None, int]]:
    """Parse lines like '3. DBS WWMC (HJ): 11th' or
    '11. UOB Visa Signature: last day of month | cycle:13'."""
    cards = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\d+\.\s*(.+?):\s*(.+)$", line)
        if not m:
            continue
        name, due_text = m.group(1).strip(), m.group(2).strip()

        cycle_start = 1
        cycle_match = re.search(r"\|\s*cycle:\s*(\d+)", due_text)
        if cycle_match:
            cycle_start = int(cycle_match.group(1))
            due_text = due_text[: cycle_match.start()].strip()

        due_day: str | None = due_text
        if "no due date" in due_text.lower():
            due_day = None

        cards.append((name, due_day, cycle_start))
    return cards


def parse_merchant_aliases(path: Path) -> list[tuple[str, str]]:
    aliases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        merchant, category = cells
        if merchant in ("Merchant", "---") or not merchant or not category:
            continue
        aliases.append((merchant, category))
    return aliases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "sir-reminds-a-lot",
        help="Path to the v1 repo (default: ../sir-reminds-a-lot)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("./data/bot.db"),
        help="Path to the v2 SQLite database (default: ./data/bot.db)",
    )
    args = parser.parse_args()

    files = {
        "categories": args.source / "categories.md",
        "cards": args.source / "creditcards.md",
        "aliases": args.source / "merchant_categories.md",
    }
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        print(f"error: source file(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 1

    categories = parse_categories(files["categories"])
    cards = parse_cards(files["cards"])
    aliases = parse_merchant_aliases(files["aliases"])

    db.init(args.db)
    for name in categories:
        db.add_category(name)
    for name, due_day, cycle_start in cards:
        db.add_card(name, due_day, cycle_start)
    for merchant, category in aliases:
        db.add_merchant_alias(merchant, category)

    print(f"Migrated into {args.db}:")
    print(f"  {len(categories)} categories")
    print(f"  {len(cards)} cards")
    print(f"  {len(aliases)} merchant aliases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
