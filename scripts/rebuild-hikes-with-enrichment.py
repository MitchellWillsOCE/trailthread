#!/usr/bin/env python3
"""
Rebuild hikes.db from the (now corrected) seed file but preserve enrichment data
(summary, tagline, tips, photos, enriched flag) from the existing DB by matching
trail names. Run this instead of build-hikes-db.py when you want to keep prior
Wikipedia/Wikimedia work.

Usage:
  python scripts/rebuild-hikes-with-enrichment.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "Trip" / "hikes" / "hikes.db"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass


def safe(t: str) -> str:
    return str(t).encode("ascii", "replace").decode("ascii")


def normalize_name(n: str) -> str:
    return " ".join((n or "").lower().split())


def snapshot_enrichment(db: Path) -> dict[str, dict]:
    if not db.is_file():
        return {}
    conn = sqlite3.connect(db, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT id, name, summary, tagline, tips_json, photos_json, enriched FROM hikes"
    ))
    conn.close()
    snapshot = {}
    for r in rows:
        if r["enriched"] or (r["photos_json"] and r["photos_json"] != "[]"):
            snapshot[normalize_name(r["name"])] = {
                "summary": r["summary"],
                "tagline": r["tagline"],
                "tips_json": r["tips_json"],
                "photos_json": r["photos_json"],
                "enriched": r["enriched"],
            }
    return snapshot


def restore_enrichment(db: Path, snapshot: dict[str, dict]) -> int:
    if not snapshot or not db.is_file():
        return 0
    conn = sqlite3.connect(db, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT id, name FROM hikes"))
    restored = 0
    for r in rows:
        snap = snapshot.get(normalize_name(r["name"]))
        if not snap:
            continue
        conn.execute(
            """
            UPDATE hikes
               SET summary    = ?,
                   tagline    = ?,
                   tips_json  = ?,
                   photos_json= ?,
                   enriched   = ?
             WHERE id = ?
            """,
            (
                snap["summary"],
                snap["tagline"],
                snap["tips_json"],
                snap["photos_json"],
                snap["enriched"],
                r["id"],
            ),
        )
        restored += 1
    conn.commit()
    conn.close()
    return restored


def main() -> None:
    print("Snapshotting enrichment from existing DB…")
    snapshot = snapshot_enrichment(DB_PATH)
    print(f"  preserved {len(snapshot)} enriched/photographed trails")

    print("Running build-hikes-db.py…")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build-hikes-db.py")],
        cwd=str(ROOT),
        check=False,
    )
    if proc.returncode != 0:
        print(f"build-hikes-db.py failed with code {proc.returncode}")
        sys.exit(proc.returncode)

    print("Restoring enrichment by name match…")
    restored = restore_enrichment(DB_PATH, snapshot)
    print(f"  restored {restored}/{len(snapshot)} trail enrichments")


if __name__ == "__main__":
    main()
