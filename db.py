from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

_conn: sqlite3.Connection | None = None
_WRITE_PROBE_CATEGORY = "__sir_reminds_write_probe__"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    due_day      TEXT,
    cycle_start  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS card_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    category       TEXT    NOT NULL UNIQUE,
    recommendation TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_aliases (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant TEXT    NOT NULL UNIQUE,
    category TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS spend_entries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT    NOT NULL,
    amount    TEXT    NOT NULL,
    card      TEXT    NOT NULL,
    category  TEXT    NOT NULL,
    remarks   TEXT
);
"""


class Card(NamedTuple):
    name: str
    due_day: str | None
    cycle_start: int


class SpendEntry(NamedTuple):
    timestamp: str
    amount: str
    card: str
    category: str
    remarks: str | None = None


class DatabasePermissionError(RuntimeError):
    pass


def _permission_message(path: Path, detail: str) -> str:
    return (
        f"SQLite database is not writable: {path}. {detail} "
        "Check that DATABASE_PATH points to a writable location and that the "
        "service user owns both the database file and its parent directory."
    )


def _validate_writable_path(path: Path) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatabasePermissionError(
            _permission_message(path, f"Could not create parent directory {parent}: {exc}.")
        ) from exc

    if not parent.is_dir():
        raise DatabasePermissionError(
            _permission_message(path, f"Parent path {parent} is not a directory.")
        )
    if not os.access(parent, os.W_OK):
        raise DatabasePermissionError(
            _permission_message(path, f"Parent directory {parent} is not writable.")
        )
    if path.exists() and not os.access(path, os.W_OK):
        raise DatabasePermissionError(
            _permission_message(path, "Database file exists but is not writable.")
        )


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(spend_entries)")}
    if "remarks" not in cols:
        conn.execute("ALTER TABLE spend_entries ADD COLUMN remarks TEXT")


def _assert_sqlite_writable(conn: sqlite3.Connection, path: Path) -> None:
    try:
        conn.execute("SAVEPOINT write_probe")
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (_WRITE_PROBE_CATEGORY,))
        conn.execute("ROLLBACK TO write_probe")
        conn.execute("RELEASE write_probe")
    except sqlite3.OperationalError as exc:
        raise DatabasePermissionError(
            _permission_message(path, f"SQLite rejected a write probe: {exc}.")
        ) from exc


def init(path: Path) -> None:
    global _conn
    path = path.expanduser()
    _validate_writable_path(path)
    _conn = sqlite3.connect(str(path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(_SCHEMA)
    _migrate(_conn)
    _assert_sqlite_writable(_conn, path)
    _conn.commit()


def _db() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db.init() must be called before any DB operation")
    return _conn


# ── Cards ─────────────────────────────────────────────────────────────────────

def get_cards() -> list[Card]:
    rows = _db().execute(
        "SELECT name, due_day, cycle_start FROM cards ORDER BY name"
    ).fetchall()
    return [Card(r["name"], r["due_day"], r["cycle_start"]) for r in rows]


def add_card(name: str, due_day: str | None, cycle_start: int = 1) -> None:
    _db().execute(
        "INSERT OR REPLACE INTO cards (name, due_day, cycle_start) VALUES (?, ?, ?)",
        (name, due_day, cycle_start),
    )
    _db().commit()


def remove_card(name: str) -> None:
    _db().execute("DELETE FROM cards WHERE name = ?", (name,))
    _db().commit()


# ── Categories ────────────────────────────────────────────────────────────────

def get_categories() -> list[str]:
    rows = _db().execute("SELECT name FROM categories ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def add_category(name: str) -> None:
    _db().execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
    _db().commit()


def remove_category(name: str) -> None:
    _db().execute("DELETE FROM categories WHERE name = ?", (name,))
    _db().commit()


# ── Card rules ────────────────────────────────────────────────────────────────

def get_card_rules() -> list[tuple[str, str]]:
    rows = _db().execute(
        "SELECT category, recommendation FROM card_rules ORDER BY category"
    ).fetchall()
    return [(r["category"], r["recommendation"]) for r in rows]


def set_card_rule(category: str, recommendation: str) -> None:
    _db().execute(
        "INSERT OR REPLACE INTO card_rules (category, recommendation) VALUES (?, ?)",
        (category, recommendation),
    )
    _db().commit()


def remove_card_rule(category: str) -> None:
    _db().execute("DELETE FROM card_rules WHERE category = ?", (category,))
    _db().commit()


# ── Merchant aliases ──────────────────────────────────────────────────────────

def get_merchant_aliases() -> list[tuple[str, str]]:
    rows = _db().execute(
        "SELECT merchant, category FROM merchant_aliases ORDER BY merchant"
    ).fetchall()
    return [(r["merchant"], r["category"]) for r in rows]


def add_merchant_alias(merchant: str, category: str) -> None:
    _db().execute(
        "INSERT OR REPLACE INTO merchant_aliases (merchant, category) VALUES (?, ?)",
        (merchant, category),
    )
    _db().commit()


def remove_merchant_alias(merchant: str) -> None:
    _db().execute("DELETE FROM merchant_aliases WHERE merchant = ?", (merchant,))
    _db().commit()


# ── Spend entries ─────────────────────────────────────────────────────────────

def append_spend(
    timestamp: datetime, amount: Decimal, card: str, category: str, remarks: str | None = None
) -> None:
    _db().execute(
        "INSERT INTO spend_entries (timestamp, amount, card, category, remarks) VALUES (?, ?, ?, ?, ?)",
        (timestamp.strftime("%Y-%m-%d %H:%M:%S"), str(amount), card, category, remarks or None),
    )
    _db().commit()


def _row_to_entry(r: sqlite3.Row) -> SpendEntry:
    return SpendEntry(r["timestamp"], r["amount"], r["card"], r["category"], r["remarks"])


def get_all_spend_rows() -> list[SpendEntry]:
    rows = _db().execute(
        "SELECT timestamp, amount, card, category, remarks FROM spend_entries ORDER BY timestamp"
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def get_spend_rows_in_range(start: date, end: date) -> list[SpendEntry]:
    rows = _db().execute(
        "SELECT timestamp, amount, card, category, remarks FROM spend_entries "
        "WHERE date(timestamp) BETWEEN ? AND ? ORDER BY timestamp",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def get_last_spend() -> SpendEntry | None:
    row = _db().execute(
        "SELECT timestamp, amount, card, category, remarks FROM spend_entries ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _row_to_entry(row) if row else None


def delete_last_spend() -> SpendEntry | None:
    row = _db().execute(
        "SELECT id, timestamp, amount, card, category, remarks FROM spend_entries ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    _db().execute("DELETE FROM spend_entries WHERE id = ?", (row["id"],))
    _db().commit()
    return _row_to_entry(row)
