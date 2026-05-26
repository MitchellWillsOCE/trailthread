#!/usr/bin/env python3
"""Add highlights_json column to existing cities.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "Trip" / "cities" / "cities.db"


def main() -> None:
    conn = sqlite3.connect(DB)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cities)").fetchall()}
    if "highlights_json" not in cols:
        conn.execute("ALTER TABLE cities ADD COLUMN highlights_json TEXT NOT NULL DEFAULT '[]'")
        conn.commit()
        print("Added highlights_json column.", flush=True)
    else:
        print("highlights_json already present.", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
