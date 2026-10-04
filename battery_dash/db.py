"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like rows."""
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")  # lets the dashboard read while cron writes
    return con


def init_db(con: sqlite3.Connection) -> None:
    """Create tables, indexes and views if they do not exist yet."""
    con.executescript(SCHEMA_PATH.read_text())
    con.commit()
