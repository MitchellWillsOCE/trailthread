#!/usr/bin/env python3
"""Merge curated Australia expansion data into the Oceania catalogs.

This worker keeps the source seed file as the system of record, then optionally
reruns the Oceania seeder so SQLite catalogs and fallback JSON stay aligned.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OCEANIA_SEED = ROOT / "scripts" / "data" / "oceania-seed.json"
EXPANSION_SEED = ROOT / "scripts" / "data" / "australia-expansion-seed.json"
SEED_OCEANIA = ROOT / "scripts" / "seed-oceania.py"
BUILD_CITIES_DB = ROOT / "scripts" / "build-cities-db.py"
CITIES_DB = ROOT / "Trip" / "cities" / "cities.db"
COLLECTIONS = ("cities", "parks", "pois", "hikes")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_err = None
    for attempt in range(8):
        try:
            tmp.replace(path)
            return
        except OSError as err:
            last_err = err
            time.sleep(0.35 * (attempt + 1))
    path.write_text(text, encoding="utf-8")
    tmp.unlink(missing_ok=True)
    if last_err:
        print(f"warn: wrote {path.name} directly after {last_err}", flush=True)


def normalize_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def row_key(row: dict) -> str:
    if row.get("id"):
        return f"id:{row['id']}"
    name = normalize_key(row.get("name", ""))
    country = normalize_key(row.get("country", ""))
    return f"name:{name}|{country}"


def merge_photos(existing: list, incoming: list) -> list:
    merged = []
    seen = set()
    for entry in [*(existing or []), *(incoming or [])]:
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or entry.get("src") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(entry)
    return merged


def merge_collection(current: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    by_key = {row_key(row): dict(row) for row in current}
    added = 0
    updated = 0
    for row in incoming:
        key = row_key(row)
        if key in by_key:
            base = by_key[key]
            photos = merge_photos(base.get("photos", []), row.get("photos", []))
            base.update(row)
            base["photos"] = photos
            updated += 1
        else:
            by_key[key] = dict(row)
            added += 1
    return list(by_key.values()), added, updated


def run_oceania_seed() -> None:
    try:
        subprocess.run([sys.executable, str(SEED_OCEANIA)], cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        print("Oceania seed failed; rebuilding city DB from generated JSON and retrying once.", flush=True)
        subprocess.run([sys.executable, str(BUILD_CITIES_DB)], cwd=ROOT, check=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{CITIES_DB}{suffix}").unlink(missing_ok=True)
        subprocess.run([sys.executable, str(SEED_OCEANIA)], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge curated Australia expansion rows into Oceania seed data.")
    parser.add_argument("--expansion", type=Path, default=EXPANSION_SEED, help="Expansion JSON payload")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    parser.add_argument("--no-apply", action="store_true", help="Only update oceania-seed.json; do not reseed SQLite catalogs")
    args = parser.parse_args()

    seed = read_json(OCEANIA_SEED)
    expansion = read_json(args.expansion)
    totals = {}

    for collection in COLLECTIONS:
        merged, added, updated = merge_collection(seed.get(collection, []), expansion.get(collection, []))
        seed[collection] = merged
        totals[collection] = {"added": added, "updated": updated, "total": len(merged)}

    for collection, stats in totals.items():
        print(
            f"{collection}: +{stats['added']} updated={stats['updated']} total={stats['total']}",
            flush=True,
        )

    if args.dry_run:
        print("dry run: no files changed", flush=True)
        return

    write_json(OCEANIA_SEED, seed)
    if not args.no_apply:
        run_oceania_seed()


if __name__ == "__main__":
    main()
