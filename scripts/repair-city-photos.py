#!/usr/bin/env python3
"""Validate city photo URLs and replace broken entries with viewable images."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio  # noqa: E402

import enrichment_sources as src  # noqa: E402
from photo_validation import (  # noqa: E402
    filter_viewable_photos,
    parse_photos_json,
)

DB_PATH = ROOT / "Trip" / "cities" / "cities.db"
MIN_PHOTOS = 1
STUB_PHRASE = "future deep-dive"
MIN_GENERAL_LEN = 72

UPDATE_SQL = """
    UPDATE cities SET
        photos_json = ?, enriched = ?, updated_at = datetime('now')
    WHERE id = ?
"""

_worker_photos = None
_db_lock = threading.Lock()
_refetch_enabled = True


def load_photo_module():
    path = ROOT / "scripts" / "fetch-location-photos.py"
    spec = importlib.util.spec_from_file_location("fetch_photos", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def city_qualifies_for_card(general: str, photos: list[dict]) -> bool:
    text = (general or "").strip()
    if STUB_PHRASE in text.lower():
        return False
    if len(text) < MIN_GENERAL_LEN:
        return False
    if len(photos) < MIN_PHOTOS:
        return False
    return True


def merge_photo_lists(*lists: list[dict], name: str = "", cap: int = 8) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for photos in lists:
        for entry in photos or []:
            if isinstance(entry, str):
                entry = {"url": entry, "caption": name}
            url = (entry.get("url") or entry.get("src") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(entry)
    return filter_viewable_photos(merged, cap=cap, name=name)


def fetch_replacement_photos(name: str, country: str, lat: float, lng: float, photos_mod) -> list[dict]:
    try:
        bundle = src.merge_city_bundle(
            name,
            country,
            lat,
            lng,
            use_commons_geosearch=True,
            commons_collector=photos_mod.collect_photos,
        )
        time.sleep(0.35)
        extras = photos_mod.collect_photos(name, country, lng, lat)
        raw = src.dedupe_photos(bundle.photos + extras, cap=12)
        return filter_viewable_photos(raw, cap=8, name=name)
    except Exception:
        # Commons-only fallback when Wikidata/DBpedia throttle.
        time.sleep(1.5)
        try:
            extras = photos_mod.collect_photos(name, country, lng, lat)
            return filter_viewable_photos(extras, cap=8, name=name)
        except Exception:
            return []


def fetch_city_ids(
    *, tier: str, region: str, limit: int, all_cities: bool, empty_photos_only: bool
) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    if empty_photos_only:
        query = """
            SELECT id FROM cities
            WHERE source != 'trip'
              AND (photos_json IS NULL OR photos_json = '[]' OR photos_json = '')
        """
    elif all_cities:
        query = "SELECT id FROM cities WHERE source != 'trip'"
    else:
        query = """
            SELECT id FROM cities
            WHERE source != 'trip'
              AND (
                (photos_json IS NOT NULL AND photos_json != '[]' AND photos_json != '')
                OR enriched = 1
                OR (
                  tier IN ('major', 'regional')
                  AND (photos_json IS NULL OR photos_json = '[]' OR photos_json = '')
                )
              )
        """
    params: list = []
    if region != "all":
        query += " AND region_id = ?"
        params.append(region)
    if tier != "all":
        query += " AND tier = ?"
        params.append(tier)
    query += " ORDER BY pop DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    ids = [row[0] for row in conn.execute(query, params).fetchall()]
    conn.close()
    return ids


def repair_city(city_id: str) -> tuple[str, bool, str]:
    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchone()
        if not row:
            return city_id, False, "not found"

        name = row["name"]
        existing = parse_photos_json(row["photos_json"])
        before_count = len(existing)
        valid = merge_photo_lists(existing, name=name)

        refetched = False
        if len(valid) < MIN_PHOTOS and _refetch_enabled and row["source"] != "trip":
            fetched = fetch_replacement_photos(name, row["country"], row["lat"], row["lng"], _worker_photos)
            if fetched:
                valid = merge_photo_lists(valid, fetched, name=name)
                refetched = True

        after_count = len(valid)
        general = row["general"] or ""
        enriched = 1 if city_qualifies_for_card(general, valid) else 0
        new_json = json.dumps(valid, ensure_ascii=False)
        changed = new_json != (row["photos_json"] or "[]") or enriched != row["enriched"]

        if changed:
            with _db_lock:
                conn.execute(UPDATE_SQL, (new_json, enriched, city_id))
                conn.commit()

        if before_count > after_count and after_count >= MIN_PHOTOS:
            detail = f"{name}: {before_count}->{after_count} photos (stripped broken)"
        elif refetched and after_count >= MIN_PHOTOS:
            detail = f"{name}: refetched -> {after_count} viewable"
        elif before_count > 0 and after_count == 0:
            detail = f"{name}: no viewable photos ({before_count} removed)"
        elif changed:
            detail = f"{name}: enriched={enriched}, photos={after_count}"
        else:
            detail = f"{name}: ok ({after_count})"

        return city_id, True, detail
    except Exception as err:
        return city_id, False, str(err)
    finally:
        conn.close()


def _init_worker() -> None:
    global _worker_photos
    _worker_photos = load_photo_module()
    time.sleep(random.uniform(0, 1.0))


def default_workers(requested: int) -> int:
    cpus = os.cpu_count() or 4
    if requested > 0:
        return max(1, requested)
    return max(1, min(cpus - 2, 6))


def print_stats() -> None:
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    with_photos = conn.execute(
        "SELECT COUNT(*) FROM cities WHERE photos_json IS NOT NULL AND photos_json != '[]'"
    ).fetchone()[0]
    enriched = conn.execute("SELECT COUNT(*) FROM cities WHERE enriched = 1").fetchone()[0]
    conn.close()
    print(f"Database: {with_photos}/{total} cities with photos_json; {enriched} enriched cards.", flush=True)


def main() -> None:
    global _refetch_enabled

    parser = argparse.ArgumentParser(description="Replace broken city photos with viewable images.")
    parser.add_argument("--limit", type=int, default=0, help="Max cities to process (0 = all matching)")
    parser.add_argument("--tier", choices=["major", "regional", "town", "all"], default="all")
    parser.add_argument("--region", default="all", help="region_id filter (default: all)")
    parser.add_argument(
        "--all-cities",
        action="store_true",
        help="Process every non-trip city (default: rows with photos or enriched cards)",
    )
    parser.add_argument(
        "--empty-photos-only",
        action="store_true",
        help="Only cities with no photos_json entries",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Drop broken URLs only; do not fetch replacements from Commons",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=0, help="Parallel threads (0 = auto, max 6)")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    configure_stdio()

    if not DB_PATH.is_file():
        raise SystemExit(f"Missing {DB_PATH}. Run: npm run build:db")

    _refetch_enabled = not args.validate_only
    worker_count = default_workers(args.workers)
    city_ids = fetch_city_ids(
        tier=args.tier,
        region=args.region,
        limit=args.limit,
        all_cities=args.all_cities,
        empty_photos_only=args.empty_photos_only,
    )

    if not city_ids:
        print("No cities matched.", flush=True)
        print_stats()
        return

    mode = "validate+refetch" if _refetch_enabled else "validate-only"
    print(
        f"Repairing photos for {len(city_ids)} cities ({mode}, workers={worker_count})…",
        flush=True,
    )

    if args.dry_run:
        for cid in city_ids[:25]:
            print(f"  would repair: {cid}")
        if len(city_ids) > 25:
            print(f"  … and {len(city_ids) - 25} more")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()

    _init_worker()
    done = 0
    failed = 0
    stripped = 0
    refetched = 0

    if worker_count == 1:
        for index, city_id in enumerate(city_ids, start=1):
            cid, ok, msg = repair_city(city_id)
            if ok:
                done += 1
                if "stripped broken" in msg or "removed" in msg:
                    stripped += 1
                if "refetched" in msg:
                    refetched += 1
            else:
                failed += 1
                print(f"  skip {cid}: {msg}", flush=True)
            if args.progress or index % 20 == 0 or index == len(city_ids):
                print(f"  {index}/{len(city_ids)} — {msg}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=worker_count, initializer=_init_worker) as pool:
            futures = {pool.submit(repair_city, cid): cid for cid in city_ids}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                cid, ok, msg = future.result()
                if ok:
                    done += 1
                    if "stripped broken" in msg or "removed" in msg:
                        stripped += 1
                    if "refetched" in msg:
                        refetched += 1
                else:
                    failed += 1
                    if failed <= 20:
                        print(f"  skip {cid}: {msg}", flush=True)
                if args.progress or completed % 25 == 0 or completed == len(city_ids):
                    print(f"  {completed}/{len(city_ids)} — last: {msg}", flush=True)

    print(
        f"Done. Processed {done} cities ({stripped} stripped, {refetched} refetched, {failed} failed).",
        flush=True,
    )
    print_stats()


if __name__ == "__main__":
    main()
