#!/usr/bin/env python3
"""Enrich landmark / POI rows with summaries, photos, and tips."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio  # noqa: E402
from catalog_paths import POI_DB  # noqa: E402
import enrichment_sources as src  # noqa: E402
from photo_validation import filter_viewable_photos  # noqa: E402
from text_phrase import highlight_line, sentences, summary_paragraph  # noqa: E402
from place_activities import poi_activities as _pool_poi_activities, poi_tips as _pool_poi_tips  # noqa: E402

TIPS_PATH = ROOT / "scripts" / "data" / "country-travel-tips.json"
MIN_SUMMARY = 60
MIN_PHOTOS = 1

UPDATE_SQL = """
    UPDATE pois SET
        summary = ?, tagline = ?, activities_json = ?, tips_json = ?,
        photos_json = ?, highlights_json = ?, enriched = ?, updated_at = datetime('now')
    WHERE id = ?
"""

CATEGORY_LABELS = {
    "fortress": "historic fortress",
    "mountain": "mountain summit",
    "monument": "historic monument",
    "heritage": "heritage site",
    "landmark": "landmark",
}


def load_photos_mod():
    path = ROOT / "scripts" / "fetch-location-photos.py"
    spec = importlib.util.spec_from_file_location("fetch_photos", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pick_tips(country: str, poi_id: str, tips_db: dict, *, category: str = "landmark") -> list[str]:
    pool_tips = _pool_poi_tips(category or "landmark", f"poi:{poi_id}")
    country_pool = tips_db.get(country) or []
    if country_pool:
        offset = sum(ord(c) for c in poi_id) % len(country_pool)
        pool_tips.append(country_pool[offset])
    return pool_tips[:4]


def load_text_bundle(name: str, country: str, lat: float, lng: float) -> src.PlaceBundle:
    try:
        return src.merge_city_bundle(name, country, lat, lng, use_commons_geosearch=False)
    except Exception:
        return src.PlaceBundle()


def gather_poi_photos(name: str, country: str, lat: float, lng: float, bundle: src.PlaceBundle, photos_mod) -> list[dict]:
    photos: list[dict] = []
    try:
        photos = filter_viewable_photos(photos_mod.collect_photos(name, country, lng, lat))
    except Exception:
        photos = []
    for item in bundle.photos or []:
        if item.get("url") and len(photos) < 6:
            photos.append(item)
    return photos[:6]


def enrich_poi(row: dict, photos_mod, tips_db: dict) -> dict:
    name = row["name"]
    country = row["country"] or "Europe"
    category = row.get("category") or "heritage"
    lat = float(row["lat"])
    lng = float(row["lng"])
    kind = CATEGORY_LABELS.get(category, "point of interest")

    bundle = load_text_bundle(name, country, lat, lng)
    extract = bundle.extract or bundle.description or ""
    summary = summary_paragraph(extract, 380) if extract else ""
    if len(summary) < MIN_SUMMARY:
        summary = (
            f"{name} is a notable {kind} in {country}, "
            f"often visited for its scenery, history, and photo opportunities."
        )

    activities = _pool_poi_activities(category or "landmark", f"poi:{row['id'] or name}")

    photos = gather_poi_photos(name, country, lat, lng, bundle, photos_mod)

    highlights = []
    for entry in photos[:4]:
        cap = entry.get("caption") or name
        highlights.append({"title": cap[:48], "caption": cap, "image": entry.get("url")})

    # Preserve curated taglines from the seed file; only synthesise a new tagline
    # when the row has no existing curated copy.
    existing_tagline = (row.get("tagline") or "").strip()
    is_curated = (row.get("source") or "").lower() == "curated"
    if is_curated and existing_tagline:
        tagline = existing_tagline
    else:
        tagline = summary_paragraph(bundle.description or name, 72) or f"Explore {name}"
    tips = pick_tips(country, row["id"], tips_db, category=category)
    enriched = 1 if len(summary) >= MIN_SUMMARY and len(photos) >= MIN_PHOTOS else 0

    return {
        "summary": summary[:520],
        "tagline": tagline[:160],
        "activities_json": json.dumps(activities[:4], ensure_ascii=False),
        "tips_json": json.dumps(tips, ensure_ascii=False),
        "photos_json": json.dumps(photos[:6], ensure_ascii=False),
        "highlights_json": json.dumps(highlights[:4], ensure_ascii=False),
        "enriched": enriched,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich POI / landmark catalog.")
    parser.add_argument("--limit", type=int, default=0, help="Max POIs (0 = all pending)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-min", type=float, default=2.0)
    parser.add_argument("--sleep-max", type=float, default=4.0)
    args = parser.parse_args()
    configure_stdio()

    if not POI_DB.is_file():
        raise SystemExit(f"Missing {POI_DB}. Run: npm run build:poi")

    tips_db = json.loads(TIPS_PATH.read_text(encoding="utf-8")) if TIPS_PATH.is_file() else {}
    photos_mod = load_photos_mod()

    conn = sqlite3.connect(POI_DB)
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM pois WHERE 1=1"
    if not args.force:
        q += " AND enriched = 0"
    q += " ORDER BY popularity DESC"
    if args.limit:
        q += " LIMIT ?"
        rows = conn.execute(q, (args.limit,)).fetchall()
    else:
        rows = conn.execute(q).fetchall()

    print(f"Enriching {len(rows)} POIs…", flush=True)
    done = 0
    for row in rows:
        data = dict(row)
        try:
            payload = enrich_poi(data, photos_mod, tips_db)
        except Exception as err:
            print(f"  skip {data['name']}: {err}", flush=True)
            time.sleep(5)
            continue
        if args.dry_run:
            print(f"  would enrich: {data['name']}", flush=True)
            continue
        conn.execute(
            UPDATE_SQL,
            (
                payload["summary"],
                payload["tagline"],
                payload["activities_json"],
                payload["tips_json"],
                payload["photos_json"],
                payload["highlights_json"],
                payload["enriched"],
                data["id"],
            ),
        )
        conn.commit()
        done += 1
        print(f"  {data['name']} ok (photos={len(json.loads(payload['photos_json']))})", flush=True)
        time.sleep(random.uniform(args.sleep_min, args.sleep_max))

    conn.close()
    print(f"Done. Enriched {done} POIs.", flush=True)


if __name__ == "__main__":
    main()
