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
DB_PATH = ROOT / "Trip" / "parks" / "parks.db"
MANIFEST_PATH = ROOT / "Trip" / "parks" / "manifest.json"


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


def main() -> None:
    if not SEED_PATH.is_file():
        raise SystemExit(f"Missing {SEED_PATH}")

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
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
            iucn_category, source, enriched, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rows = []
    for entry in seeds:
        name = entry.get("name", "").strip()
        country = entry.get("country", "").strip()
        if not name:
            continue
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
                "europe",
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
                None,
                f"Explore {name}",
                entry.get("stay") or "1–2 days",
                "[]",
                "[]",
                "[]",
                "[]",
                "II",
                "seed",
                0,
                now,
            )
        )

    conn.executemany(insert, rows)
    conn.execute(
        "INSERT INTO regions (id, label, park_count) VALUES (?, ?, ?)",
        ("europe", "Europe", len(rows)),
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
        "regions": [{"id": "europe", "label": "Europe", "count": len(rows)}],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Built {len(rows)} parks -> {DB_PATH}", flush=True)


if __name__ == "__main__":
    main()
