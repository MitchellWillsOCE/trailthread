#!/usr/bin/env python3
"""Build European national parks catalog in SQLite from seed data (+ optional OSM lookup)."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "scripts" / "schema" / "parks.sql"
SEED_PATH = ROOT / "scripts" / "data" / "europe-parks-seed.json"
OCEANIA_SEED_PATH = ROOT / "scripts" / "data" / "oceania-seed.json"
DB_PATH = ROOT / "Trip" / "parks" / "parks.db"
MANIFEST_PATH = ROOT / "Trip" / "parks" / "manifest.json"

REGIONS = {
    "europe": "Europe",
    "oceania": "Oceania",
}


def slugify(name: str, country: str) -> str:
    raw = f"{name}-{country}".lower()
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return raw[:80] or "park"


def tier_for(popularity: int, area_km2: float) -> str:
    if popularity >= 88 or area_km2 >= 800:
        return "major"
    if popularity >= 75 or area_km2 >= 100:
        return "regional"
    return "local"


def bbox_from_point(lat: float, lng: float, km: float = 18.0) -> tuple[float, float, float, float]:
    dlat = km / 111.0
    dlng = km / (111.0 * max(0.35, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def load_seed_rows() -> list[dict]:
    rows = []
    for entry in json.loads(SEED_PATH.read_text(encoding="utf-8")):
        rows.append({**entry, "region_id": "europe"})
    if OCEANIA_SEED_PATH.is_file():
        oceania = json.loads(OCEANIA_SEED_PATH.read_text(encoding="utf-8"))
        for entry in oceania.get("parks", []):
            rows.append({**entry, "region_id": "oceania"})
    return rows


def main() -> None:
    if not SEED_PATH.is_file():
        raise SystemExit(f"Missing {SEED_PATH}")

    seeds = load_seed_rows()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".db.build.tmp")
    if tmp.exists():
        tmp.unlink()

    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()

    insert = """
        INSERT INTO parks (
            id, region_id, osm_id, name, country, cc, lat, lng, area_km2, biodiversity,
            popularity, tier, west, south, east, north,
            summary, tagline, stay, activities_json, tips_json, photos_json, highlights_json,
            iucn_category, source, enriched, updated_at, category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rows = []
    counts: dict[str, int] = {}
    for entry in seeds:
        name = entry.get("name", "").strip()
        country = entry.get("country", "").strip()
        if not name:
            continue
        region_id = entry.get("region_id", "europe")
        lat = float(entry.get("lat", 0))
        lng = float(entry.get("lng", 0))
        area = float(entry.get("area_km2") or 50)
        pop = int(entry.get("popularity") or 70)
        bio = max(1, min(5, int(entry.get("biodiversity") or 3)))
        west, south, east, north = bbox_from_point(lat, lng, km=min(40, math.sqrt(area) * 2.5))
        park_id = slugify(name, country)
        rows.append(
            (
                park_id,
                region_id,
                entry.get("osm_id"),
                name,
                country,
                (entry.get("cc") or "").lower(),
                lat,
                lng,
                area,
                bio,
                pop,
                tier_for(pop, area),
                west,
                south,
                east,
                north,
                entry.get("summary"),
                entry.get("tagline") or f"Explore {name}",
                entry.get("stay") or "1–2 days",
                json.dumps(entry.get("activities") or [], ensure_ascii=False),
                json.dumps(entry.get("tips") or [], ensure_ascii=False),
                json.dumps(entry.get("photos") or [], ensure_ascii=False),
                json.dumps(entry.get("highlights") or [], ensure_ascii=False),
                entry.get("iucn_category") or "II",
                entry.get("source", "seed"),
                1 if region_id == "oceania" else 0,
                now,
                entry.get("category", ""),
            )
        )
        counts[region_id] = counts.get(region_id, 0) + 1

    conn.executemany(insert, rows)
    for region_id, count in counts.items():
        conn.execute(
            "INSERT INTO regions (id, label, park_count) VALUES (?, ?, ?)",
            (region_id, REGIONS.get(region_id, region_id.title()), count),
        )
    conn.commit()
    conn.close()

    alt = DB_PATH.with_name("parks.db.new")
    try:
        if DB_PATH.exists():
            DB_PATH.unlink()
        tmp.replace(DB_PATH)
        if alt.exists():
            alt.unlink(missing_ok=True)
    except OSError as err:
        if alt.exists():
            alt.unlink(missing_ok=True)
        tmp.replace(alt)
        print(
            f"Warning: could not replace locked {DB_PATH} ({err}). "
            f"Wrote {alt} — API loads .new until dev server restarts."
        )

    manifest = {
        "version": 1,
        "storage": "sqlite",
        "database": "./Trip/parks/parks.db",
        "regions": [
            {"id": region_id, "label": REGIONS.get(region_id, region_id.title()), "count": counts[region_id]}
            for region_id in sorted(counts.keys(), key=lambda item: 0 if item == "europe" else 1)
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Built {len(rows)} parks -> {DB_PATH}", flush=True)


if __name__ == "__main__":
    main()
