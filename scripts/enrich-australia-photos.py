#!/usr/bin/env python3
"""Fetch and seed photos for Oceania catalog rows.

The worker updates scripts/data/oceania-seed.json first, then reruns the
Oceania seeder by default so SQLite catalogs and fallback JSON receive the same
photo arrays.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from photo_validation import filter_viewable_photos  # noqa: E402

OCEANIA_SEED = ROOT / "scripts" / "data" / "oceania-seed.json"
SEED_OCEANIA = ROOT / "scripts" / "seed-oceania.py"
BUILD_CITIES_DB = ROOT / "scripts" / "build-cities-db.py"
CITIES_DB = ROOT / "Trip" / "cities" / "cities.db"
PHOTO_HELPER = ROOT / "scripts" / "fetch-location-photos.py"
DEFAULT_COLLECTIONS = ("cities", "parks", "pois", "hikes")
PACIFIC_CCS = {
    "fj", "pg", "sb", "vu", "nc", "pf", "ws", "as", "to", "ck",
    "nu", "pw", "gu", "mp", "fm", "mh", "ki", "nr", "tv", "wf", "nf",
}
PHOTO_QUERY_ALIASES = {
    "Jatbula Trail": ["Nitmiluk National Park", "Katherine Gorge"],
    "Thorsborne Trail": ["Hinchinbrook Island", "Hinchinbrook Island National Park"],
    "Wineglass Bay Lookout Track": ["Wineglass Bay", "Freycinet National Park"],
    "Cloud 9 Fiji": ["Cloud 9 pontoon Fiji", "Malolo reef Fiji"],
    "Heart of Voh": ["Coeur de Voh", "Heart of Voh mangrove"],
    "To Sua Ocean Trench": ["To Sua Ocean Trench Samoa"],
    "Yasur / Lake Siwi area": ["Mount Yasur", "Yasur volcano Tanna"],
    "Owen Stanley Ranges / Kokoda": ["Kokoda Track", "Owen Stanley Range"],
    "War in the Pacific National Historical Park": ["Asan Beach Guam", "War in the Pacific Park Guam"],
    "Kingston and Arthur's Vale": ["Kingston Norfolk Island"],
    "We": ["We Lifou", "Wé Lifou New Caledonia"],
    "Fare": ["Fare Huahine", "Huahine Fare"],
    "London": ["London Kiritimati", "Christmas Island Kiribati"],
    "Jellyfish Lake": ["Jellyfish Lake Palau", "Ongeim'l Tketau"],
    "Nan Madol": ["Nan Madol Pohnpei"],
    "Te Rua Manga Cross-Island Track": ["Te Rua Manga", "The Needle Rarotonga"],
    "Mount Alava Adventure Trail": ["Mount Alava American Samoa"],
    "National Park of American Samoa": ["National Park of American Samoa", "Pola Island"],
    "Bouma National Heritage Park": ["Tavoro Falls", "Lavena Taveuni", "Bouma Taveuni"],
    "Te Fa'aiti Territorial Park": ["Papenoo Valley Tahiti", "Papenoo"],
    "Ritidian / Litekyan": ["Ritidian Point Guam", "Ritidian Beach"],
    "Huvalu Forest Conservation Area": ["Huvalu Forest Niue", "Niue rainforest"],
    "Mount Talau National Park": ["Mount Talau Vava'u", "Neiafu harbour"],
    "Mataniko Falls": ["Mataniko Falls Guadalcanal", "Mataniko Honiara"],
    "Parliament Haus": ["Parliament House Port Moresby", "National Parliament Papua New Guinea"],
    "Mapu'a 'a Vaea Blowholes": ["Mapu a Vaea", "Tongatapu blowholes"],
    "Kepirohi Falls": ["Kepirohi Pohnpei", "Kepirohi waterfall"],
    "Two Lovers Point": ["Puntan Dos Amantes", "Two Lovers Point Guam"],
    "Alele Museum": ["Alele Museum Majuro", "Majuro Atoll"],
    "Fautaua Valley": ["Fautaua Falls", "Fautaua Tahiti"],
    "Varirata Lookout Walk": ["Varirata National Park", "Sogeri Plateau"],
    "Mount Yasur Crater Walk": ["Mount Yasur", "Yasur volcano"],
    "Riviere Bleue Giant Kaori Walk": ["Rivière Bleue", "Riviere Bleue kaori"],
    "Lavena Coastal Walk": ["Lavena Taveuni", "Lavena coastline"],
    "Colo-i-Suva Nature Trail": ["Colo-i-Suva", "Colo i Suva forest"],
    "Moorea Belvedere Walk": ["Belvedere Moorea", "Opunohu Valley"],
    "Fautaua Waterfall Walk": ["Fautaua Falls Tahiti"],
    "Mount Talau Walk": ["Mount Talau", "Neiafu Vava'u"],
    "'Eua Clifftop Walk": ["Eua Island Tonga", "Eua cliffs"],
    "Ngardmau Waterfall Walk": ["Ngardmau Falls", "Ngardmau Palau"],
    "Mount Lamlam Walk": ["Mount Lamlam Guam"],
    "Mount Tapochau Walk": ["Mount Tapochau Saipan"],
    "Sokehs Rock": ["Sokehs Rock Pohnpei"],
    "Aorai Trail": ["Mont Aorai", "Aorai Tahiti"],
    "Lake Lanoto'o Walk": ["Lake Lanoto'o", "Lanotoo Samoa"],
}


def load_photo_helper():
    spec = importlib.util.spec_from_file_location("fetch_location_photos", PHOTO_HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    return f"name:{normalize_key(row.get('name', ''))}|{normalize_key(row.get('country', ''))}"


def merge_photo_lists(*lists: list[dict], cap: int, name: str, validate: bool) -> list[dict]:
    merged = []
    seen = set()
    for photos in lists:
        for entry in photos or []:
            if isinstance(entry, str):
                entry = {"url": entry, "caption": name}
            if not isinstance(entry, dict):
                continue
            url = (entry.get("url") or entry.get("src") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(entry)
    if validate:
        return filter_viewable_photos(merged, cap=cap, name=name)
    return merged[:cap]


def extra_commons_queries(row: dict, collection: str) -> list[str]:
    name = row.get("name", "")
    country = row.get("country", "Australia")
    queries = [f"{alias} {country}" for alias in PHOTO_QUERY_ALIASES.get(name, [])]
    queries.append(f"{name} {country}")
    if collection == "parks":
        queries.extend([f"{name} landscape", f"{name} national park"])
    elif collection == "hikes":
        queries.extend([f"{name} trail {country}", f"{name} hiking"])
    elif collection == "pois":
        queries.extend([f"{name} landmark {country}", f"{name} travel"])
    else:
        queries.extend([f"{name} skyline {country}", f"{name} city {country}"])
    return queries


def fetch_photos_for_row(
    row: dict,
    collection: str,
    max_photos: int,
    validate: bool,
    fast_commons: bool,
) -> tuple[str, list[dict], str]:
    helper = load_photo_helper()
    name = row.get("name", "")
    country = row.get("country", "Australia")
    lat = row.get("lat")
    lng = row.get("lng")
    existing = row.get("photos") or []
    fetched: list[dict] = []

    time.sleep(random.uniform(0.1, 0.8))
    try:
        if collection == "hikes" and not fast_commons:
            fetched.extend(helper.collect_trail_photos(name, country, lng, lat, limit=max_photos))
        if not fast_commons:
            fetched.extend(helper.collect_photos(name, country, lng, lat))
        for query in extra_commons_queries(row, collection):
            if len(fetched) >= max_photos * 2:
                break
            fetched.extend(helper.wiki_text_search(query, limit=8))
            time.sleep(0.15 if fast_commons else 0.45)
    except Exception as err:
        merged = merge_photo_lists(existing, cap=max_photos, name=name, validate=validate)
        return row_key(row), merged, f"{name}: fetch failed ({err}); kept {len(merged)} existing"

    merged = merge_photo_lists(existing, fetched, cap=max_photos, name=name, validate=validate)
    return row_key(row), merged, f"{name}: {len(existing)} -> {len(merged)} photos"


def parse_ccs(raw: str) -> set[str] | None:
    text = (raw or "").strip().lower()
    if text in {"*", "all"}:
        return None
    if text == "pacific":
        return set(PACIFIC_CCS)
    codes = {item.strip().lower() for item in text.split(",") if item.strip()}
    return codes or {"au"}


def iter_targets(seed: dict, collections: tuple[str, ...], ccs: set[str] | None, min_photos: int, all_rows: bool) -> list[tuple[str, dict]]:
    targets = []
    for collection in collections:
        for row in seed.get(collection, []):
            if ccs is not None and str(row.get("cc", "")).lower() not in ccs:
                continue
            if all_rows or len(row.get("photos") or []) < min_photos:
                targets.append((collection, row))
    return targets


def apply_updates(seed: dict, updates: dict[str, list[dict]]) -> None:
    for collection in DEFAULT_COLLECTIONS:
        for row in seed.get(collection, []):
            key = row_key(row)
            if key in updates:
                row["photos"] = updates[key]


def run_oceania_seed() -> None:
    try:
        subprocess.run([sys.executable, str(SEED_OCEANIA)], cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        print("Oceania seed failed; rebuilding city DB from generated JSON and retrying once.", flush=True)
        subprocess.run([sys.executable, str(BUILD_CITIES_DB)], cwd=ROOT, check=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{CITIES_DB}{suffix}").unlink(missing_ok=True)
        subprocess.run([sys.executable, str(SEED_OCEANIA)], cwd=ROOT, check=True)


def parse_collections(raw: str) -> tuple[str, ...]:
    requested = tuple(item.strip() for item in raw.split(",") if item.strip())
    invalid = [item for item in requested if item not in DEFAULT_COLLECTIONS]
    if invalid:
        raise SystemExit(f"Unknown collection(s): {', '.join(invalid)}")
    return requested or DEFAULT_COLLECTIONS


def default_workers(requested: int, total_targets: int) -> int:
    if requested > 0:
        return max(1, min(requested, total_targets))
    return max(1, min(os.cpu_count() or 1, total_targets))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and seed photos for Oceania catalog rows.")
    parser.add_argument("--collections", default=",".join(DEFAULT_COLLECTIONS), help="Comma-separated: cities,parks,pois,hikes")
    parser.add_argument("--cc", default="au", help="Country code(s): au, comma list, pacific, or all")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process after filtering")
    parser.add_argument("--workers", type=int, default=0, help="Parallel workers (0 = all CPU cores)")
    parser.add_argument("--min-photos", type=int, default=4, help="Process rows with fewer than this many photos")
    parser.add_argument("--max-photos", type=int, default=8, help="Store up to this many photos per row")
    parser.add_argument("--all", action="store_true", help="Process all matching rows even if they already have enough photos")
    parser.add_argument("--fast-commons", action="store_true", help="Use text-search only; much faster but less location-aware")
    parser.add_argument("--no-validate", action="store_true", help="Skip URL validation after fetching")
    parser.add_argument("--dry-run", action="store_true", help="Fetch/report but do not write files")
    parser.add_argument("--no-apply", action="store_true", help="Update seed JSON only; do not reseed SQLite catalogs")
    args = parser.parse_args()

    collections = parse_collections(args.collections)
    seed = read_json(OCEANIA_SEED)
    targets = iter_targets(seed, collections, parse_ccs(args.cc), args.min_photos, args.all)
    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        print("No matching rows need photos.", flush=True)
        return

    worker_count = default_workers(args.workers, len(targets))
    validate = not args.no_validate
    print(f"Fetching photos for {len(targets)} row(s) with {worker_count} worker(s).", flush=True)

    updates: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(fetch_photos_for_row, row, collection, args.max_photos, validate, args.fast_commons)
            for collection, row in targets
        ]
        for future in as_completed(futures):
            key, photos, detail = future.result()
            updates[key] = photos
            print(detail, flush=True)

    if args.dry_run:
        print("dry run: no files changed", flush=True)
        return

    apply_updates(seed, updates)
    write_json(OCEANIA_SEED, seed)
    if not args.no_apply:
        run_oceania_seed()


if __name__ == "__main__":
    main()
