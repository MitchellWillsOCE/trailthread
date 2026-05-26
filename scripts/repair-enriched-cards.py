#!/usr/bin/env python3
"""Reset enriched=1 rows that lack verified photos or real copy (so enrich can retry)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio  # noqa: E402

CITIES_DB = ROOT / "Trip" / "cities" / "cities.db"
HIKES_DB = ROOT / "Trip" / "hikes" / "hikes.db"
STUB = "future deep-dive"


def photos_count(raw: str) -> int:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return 0
    return len(data) if isinstance(data, list) else 0


def repair_cities(*, dry_run: bool) -> int:
    conn = sqlite3.connect(CITIES_DB)
    rows = conn.execute(
        "SELECT id, general, photos_json, source FROM cities WHERE enriched = 1"
    ).fetchall()
    reset_ids: list[str] = []
    for city_id, general, photos_json, source in rows:
        if source == "trip":
            continue
        g = (general or "").lower()
        if STUB in g or photos_count(photos_json) < 1 or len((general or "").strip()) < 72:
            reset_ids.append(city_id)
    if not dry_run and reset_ids:
        conn.executemany("UPDATE cities SET enriched = 0 WHERE id = ?", [(i,) for i in reset_ids])
        conn.commit()
    conn.close()
    return len(reset_ids)


def repair_hikes(*, dry_run: bool) -> int:
    if not HIKES_DB.is_file():
        return 0
    conn = sqlite3.connect(HIKES_DB)
    rows = conn.execute(
        "SELECT id, summary, photos_json FROM hikes WHERE COALESCE(enriched, 0) = 1"
    ).fetchall()
    reset_ids: list[str] = []
    for hike_id, summary, photos_json in rows:
        if photos_count(photos_json) < 1 or len((summary or "").strip()) < 80:
            reset_ids.append(hike_id)
    if not dry_run and reset_ids:
        conn.executemany("UPDATE hikes SET enriched = 0 WHERE id = ?", [(i,) for i in reset_ids])
        conn.commit()
    conn.close()
    return len(reset_ids)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    configure_stdio()

    c = repair_cities(dry_run=args.dry_run)
    h = repair_hikes(dry_run=args.dry_run)
    label = "would reset" if args.dry_run else "reset"
    print(f"Cities {label}: {c}", flush=True)
    print(f"Hikes {label}: {h}", flush=True)


if __name__ == "__main__":
    main()
