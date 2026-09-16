#!/usr/bin/env python3
"""Build European points-of-interest catalog (heritage, fortresses, mountains, monuments)."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from place_kinds import infer_poi_category, is_park_place_name, load_park_names

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "scripts" / "schema" / "poi.sql"
SEED_PATH = ROOT / "scripts" / "data" / "europe-poi-seed.json"
OCEANIA_SEED_PATH = ROOT / "scripts" / "data" / "oceania-seed.json"
TRIP_DIR = ROOT / "Trip"
DB_PATH = ROOT / "Trip" / "poi" / "poi.db"
MANIFEST_PATH = ROOT / "Trip" / "poi" / "manifest.json"
PLACE_DETAILS = ROOT / "Trip" / "place-details.json"

REGIONS = {
    "europe": "Europe",
    "oceania": "Oceania",
}


def slugify(name: str, country: str) -> str:
    raw = f"{name}-{country}".lower()
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return raw[:80] or "poi"


def tier_for(popularity: int) -> str:
    if popularity >= 92:
        return "major"
    if popularity >= 78:
        return "regional"
    return "local"


def bbox_from_point(lat: float, lng: float, km: float = 6.0) -> tuple[float, float, float, float]:
    dlat = km / 111.0
    dlng = km / (111.0 * max(0.35, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def extract_trip_heritage() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(TRIP_DIR.glob("**/*route*.geojson")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for feature in data.get("features", []):
            if feature.get("geometry", {}).get("type") != "Point":
                continue
            props = feature.get("properties") or {}
            stop = props.get("stopType", "")
            if stop not in ("heritage", "start", "end"):
                continue
            if stop in ("start", "end") and "fort" not in (props.get("name") or "").lower():
                continue
            name = (props.get("name") or "").strip()
            country = (props.get("country") or "").strip()
            coords = feature.get("geometry", {}).get("coordinates") or []
            if not name or len(coords) < 2:
                continue
            lng, lat = float(coords[0]), float(coords[1])
            rows.append(
                {
                    "name": name,
                    "country": country,
                    "cc": "",
                    "lat": lat,
                    "lng": lng,
                    "category": infer_poi_category(name),
                    "popularity": 82 if stop == "heritage" else 75,
                    "source": "journey",
                }
            )
    return rows


def merge_entry(by_key: dict[str, dict], entry: dict, *, prefer: bool = False) -> None:
    name = entry.get("name", "").strip()
    country = entry.get("country", "").strip()
    if not name:
        return
    region_id = entry.get("region_id", "europe")
    key = f"{region_id}:{slugify(name, country or region_id)}"
    entry = {
        **entry,
        "name": name,
        "country": country,
        "region_id": region_id,
        "source": entry.get("source", "curated"),
    }
    if prefer or key not in by_key:
        by_key[key] = entry
    elif by_key[key].get("source") != "curated" and entry.get("source") == "curated":
        by_key[key] = {**by_key[key], **entry}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build European POI catalog from curated seed.")
    parser.add_argument(
        "--include-journey",
        action="store_true",
        help="Also merge heritage stops from journey GeoJSON (off by default)",
    )
    args = parser.parse_args()
    park_names = load_park_names()
    place_details = {}
    if PLACE_DETAILS.is_file():
        place_details = json.loads(PLACE_DETAILS.read_text(encoding="utf-8"))

    by_key: dict[str, dict] = {}

    if SEED_PATH.is_file():
        for entry in json.loads(SEED_PATH.read_text(encoding="utf-8")):
            row = {**entry, "source": "curated", "region_id": "europe"}
            merge_entry(by_key, row, prefer=True)

    if OCEANIA_SEED_PATH.is_file():
        oceania = json.loads(OCEANIA_SEED_PATH.read_text(encoding="utf-8"))
        for entry in oceania.get("pois", []):
            row = {**entry, "source": "curated", "region_id": "oceania"}
            merge_entry(by_key, row, prefer=True)

    if args.include_journey:
        for entry in extract_trip_heritage():
            if is_park_place_name(entry["name"], park_names):
                continue
            merge_entry(by_key, entry)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".db.build.tmp")
    if tmp.exists():
        tmp.unlink()

    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()

    insert = """
        INSERT INTO pois (
            id, region_id, osm_id, name, country, cc, category, lat, lng,
            popularity, tier, west, south, east, north,
            summary, tagline, activities_json, tips_json, photos_json, highlights_json,
            source, enriched, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rows_out = []
    counts: dict[str, int] = {}
    for entry in sorted(by_key.values(), key=lambda r: (r.get("region_id", ""), r.get("country", ""), r.get("name", ""))):
        name = entry["name"]
        if is_park_place_name(name, park_names):
            continue
        region_id = entry.get("region_id", "europe")
        country = entry.get("country") or ""
        lat = float(entry.get("lat", 0))
        lng = float(entry.get("lng", 0))
        pop = int(entry.get("popularity") or 70)
        category = entry.get("category") or infer_poi_category(name)
        cc = (entry.get("cc") or "").lower()
        west, south, east, north = bbox_from_point(lat, lng)
        poi_id = slugify(name, country)
        place = place_details.get(name) or {}
        if entry.get("source") == "curated" and entry.get("tagline"):
            summary = entry.get("tagline")
            tagline = entry["tagline"]
        else:
            summary = place.get("general") or entry.get("tagline") or (
                f"Notable {category.replace('_', ' ')} in {country or 'Europe'}."
            )
            tagline = place.get("tagline") or entry.get("tagline") or f"Explore {name}"
        activities = json.dumps(place.get("activities") or [], ensure_ascii=False)
        tips = json.dumps(place.get("tips") or [], ensure_ascii=False)
        photos = json.dumps(place.get("photos") or [], ensure_ascii=False)
        highlights = json.dumps(place.get("highlights") or [], ensure_ascii=False)
        enriched = 0
        if entry.get("source") == "curated" and entry.get("tagline"):
            enriched = 0
        elif place.get("general") and len(str(place.get("general"))) > 80:
            enriched = 1

        rows_out.append(
            (
                poi_id,
                region_id,
                entry.get("osm_id"),
                name,
                country,
                cc,
                category,
                lat,
                lng,
                pop,
                tier_for(pop),
                west,
                south,
                east,
                north,
                summary[:2000] if summary else None,
                tagline[:200] if tagline else None,
                activities,
                tips,
                photos,
                highlights,
                entry.get("source", "catalog"),
                1 if region_id == "oceania" else enriched,
                now,
            )
        )
        counts[region_id] = counts.get(region_id, 0) + 1

    conn.executemany(insert, rows_out)
    for region_id, count in counts.items():
        conn.execute(
            "INSERT INTO regions (id, label, poi_count) VALUES (?, ?, ?)",
            (region_id, REGIONS.get(region_id, region_id.title()), count),
        )
    conn.commit()
    conn.close()

    if DB_PATH.exists():
        DB_PATH.unlink()
    tmp.replace(DB_PATH)

    manifest = {
        "schemaVersion": 1,
        "storage": "sqlite",
        "database": "./Trip/poi/poi.db",
        "apiBase": "/api/poi",
        "regions": [
            {"id": region_id, "label": REGIONS.get(region_id, region_id.title()), "count": counts[region_id]}
            for region_id in sorted(counts.keys(), key=lambda item: 0 if item == "europe" else 1)
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows_out)} POIs to {DB_PATH}")


if __name__ == "__main__":
    main()
