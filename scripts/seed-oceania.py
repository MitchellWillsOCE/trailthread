#!/usr/bin/env python3
"""Seed Oceania catalog data for Australia, New Zealand, and the wider Pacific.

Idempotent: updates live SQLite catalogs plus JSON/GeoJSON source artifacts so
regional map selection works in dev, production, and GeoJSON fallback modes.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "scripts" / "data" / "oceania-seed.json"
REGION_ID = "oceania"
REGION_LABEL = "Oceania"
NOW_ISO = datetime.now(timezone.utc).isoformat()

CITIES_DB = ROOT / "Trip" / "cities" / "cities.db"
HIKES_DB = ROOT / "Trip" / "hikes" / "hikes.db"
PARKS_DB = ROOT / "Trip" / "parks" / "parks.db"
POI_DB = ROOT / "Trip" / "poi" / "poi.db"

CITIES_MANIFEST = ROOT / "Trip" / "cities" / "manifest.json"
HIKES_MANIFEST = ROOT / "Trip" / "hikes" / "manifest.json"
PARKS_MANIFEST = ROOT / "Trip" / "parks" / "manifest.json"
POI_MANIFEST = ROOT / "Trip" / "poi" / "manifest.json"

CITIES_OUT_DIR = ROOT / "Trip" / "cities" / REGION_ID
HIKES_OUT_DIR = ROOT / "Trip" / "hikes" / REGION_ID
REGION_GEOJSON = ROOT / "Trip" / "geo" / "oceania-countries.geojson"
COUNTRY_POPULATIONS = ROOT / "Trip" / "cities" / "country-populations.json"
COUNTRY_TIPS = ROOT / "scripts" / "data" / "country-travel-tips.json"
COUNTRY_SEASONS = ROOT / "scripts" / "data" / "country-seasons.json"


OCEANIA_COUNTRY_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"cc": "AU", "name": "Australia"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [113.0, -35.3],
                            [114.4, -21.8],
                            [121.0, -13.6],
                            [129.0, -11.5],
                            [138.0, -10.5],
                            [146.0, -16.0],
                            [153.7, -27.6],
                            [150.2, -37.6],
                            [141.0, -38.9],
                            [130.0, -35.0],
                            [121.0, -34.8],
                            [113.0, -35.3],
                        ]
                    ],
                    [
                        [
                            [144.5, -40.6],
                            [148.4, -40.9],
                            [148.3, -43.7],
                            [145.2, -43.8],
                            [144.5, -40.6],
                        ]
                    ],
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {"cc": "NZ", "name": "New Zealand"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [172.5, -34.4],
                            [176.6, -37.0],
                            [178.6, -38.8],
                            [176.0, -41.6],
                            [172.8, -41.2],
                            [173.0, -37.6],
                            [172.5, -34.4],
                        ]
                    ],
                    [
                        [
                            [166.4, -46.7],
                            [169.6, -43.8],
                            [173.3, -41.4],
                            [174.5, -42.8],
                            [172.0, -45.3],
                            [168.5, -47.3],
                            [166.4, -46.7],
                        ]
                    ],
                ],
            },
        },
    ],
}


AUSTRALIA_SEASON = {
    "peak": ["Dec", "Jan", "Feb"],
    "shoulder": ["Mar", "Apr", "Sep", "Oct", "Nov"],
    "low": ["Jun", "Jul", "Aug"],
    "note": "Southern Australia peaks in summer, while the tropical north is most comfortable in the dry season from May to September. Red Centre hikes are best in cooler months.",
    "best": "Mar-May, Sep-Nov",
    "weather": {
        "Jan": {"high": 27, "low": 19, "rain": 85},
        "Feb": {"high": 27, "low": 19, "rain": 95},
        "Mar": {"high": 25, "low": 17, "rain": 80},
        "Apr": {"high": 22, "low": 14, "rain": 65},
        "May": {"high": 19, "low": 11, "rain": 60},
        "Jun": {"high": 16, "low": 8, "rain": 65},
        "Jul": {"high": 16, "low": 7, "rain": 55},
        "Aug": {"high": 17, "low": 8, "rain": 55},
        "Sep": {"high": 20, "low": 10, "rain": 55},
        "Oct": {"high": 22, "low": 13, "rain": 65},
        "Nov": {"high": 24, "low": 15, "rain": 75},
        "Dec": {"high": 26, "low": 18, "rain": 80},
    },
}

NEW_ZEALAND_SEASON = {
    "peak": ["Dec", "Jan", "Feb"],
    "shoulder": ["Mar", "Apr", "Oct", "Nov"],
    "low": ["Jun", "Jul", "Aug"],
    "note": "Summer is prime for Great Walks and alpine roads. Spring and autumn are quieter but changeable; winter brings snow and avalanche risk on high routes.",
    "best": "Nov-Apr",
    "weather": {
        "Jan": {"high": 22, "low": 13, "rain": 65},
        "Feb": {"high": 22, "low": 13, "rain": 55},
        "Mar": {"high": 20, "low": 11, "rain": 70},
        "Apr": {"high": 17, "low": 8, "rain": 75},
        "May": {"high": 14, "low": 6, "rain": 85},
        "Jun": {"high": 11, "low": 3, "rain": 90},
        "Jul": {"high": 10, "low": 2, "rain": 85},
        "Aug": {"high": 12, "low": 3, "rain": 80},
        "Sep": {"high": 14, "low": 5, "rain": 75},
        "Oct": {"high": 16, "low": 7, "rain": 75},
        "Nov": {"high": 18, "low": 9, "rain": 70},
        "Dec": {"high": 20, "low": 11, "rain": 70},
    },
}

SOUTH_PACIFIC_DRY_SEASON = {
    "peak": ["Jun", "Jul", "Aug", "Sep"],
    "shoulder": ["May", "Oct"],
    "low": ["Dec", "Jan", "Feb", "Mar"],
    "note": "The drier, cooler months from May to October are the most comfortable for islands, reefs, and village travel. November to April is hotter, wetter, and the main cyclone window.",
    "best": "May-Oct",
    "weather": {
        "Jan": {"high": 31, "low": 24, "rain": 280},
        "Feb": {"high": 31, "low": 24, "rain": 270},
        "Mar": {"high": 31, "low": 24, "rain": 260},
        "Apr": {"high": 30, "low": 23, "rain": 180},
        "May": {"high": 29, "low": 22, "rain": 120},
        "Jun": {"high": 28, "low": 21, "rain": 90},
        "Jul": {"high": 27, "low": 20, "rain": 80},
        "Aug": {"high": 27, "low": 20, "rain": 80},
        "Sep": {"high": 28, "low": 21, "rain": 90},
        "Oct": {"high": 29, "low": 22, "rain": 130},
        "Nov": {"high": 30, "low": 23, "rain": 190},
        "Dec": {"high": 31, "low": 24, "rain": 250},
    },
}

PNG_SEASON = {
    "peak": ["May", "Jun", "Jul", "Aug", "Sep"],
    "shoulder": ["Apr", "Oct"],
    "low": ["Dec", "Jan", "Feb"],
    "note": "The dry season is the usual window for Highlands roads and the Kokoda Track. Highland nights are cold year-round; the north coast stays hot and wet.",
    "best": "May-Sep",
    "weather": {
        "Jan": {"high": 31, "low": 23, "rain": 220},
        "Feb": {"high": 31, "low": 23, "rain": 210},
        "Mar": {"high": 30, "low": 23, "rain": 200},
        "Apr": {"high": 30, "low": 23, "rain": 180},
        "May": {"high": 29, "low": 22, "rain": 140},
        "Jun": {"high": 28, "low": 21, "rain": 110},
        "Jul": {"high": 28, "low": 21, "rain": 100},
        "Aug": {"high": 28, "low": 21, "rain": 110},
        "Sep": {"high": 29, "low": 22, "rain": 130},
        "Oct": {"high": 30, "low": 22, "rain": 160},
        "Nov": {"high": 30, "low": 23, "rain": 180},
        "Dec": {"high": 31, "low": 23, "rain": 210},
    },
}

NORTH_PACIFIC_DRY_SEASON = {
    "peak": ["Jan", "Feb", "Mar", "Apr"],
    "shoulder": ["May", "Dec"],
    "low": ["Jul", "Aug", "Sep"],
    "note": "Micronesia is usually drier from December to May. July to November is wetter, with typhoon risk in the Marianas, Guam, and Palau.",
    "best": "Dec-May",
    "weather": {
        "Jan": {"high": 29, "low": 24, "rain": 110},
        "Feb": {"high": 29, "low": 24, "rain": 90},
        "Mar": {"high": 30, "low": 24, "rain": 90},
        "Apr": {"high": 30, "low": 25, "rain": 100},
        "May": {"high": 31, "low": 25, "rain": 140},
        "Jun": {"high": 31, "low": 25, "rain": 180},
        "Jul": {"high": 31, "low": 25, "rain": 250},
        "Aug": {"high": 31, "low": 25, "rain": 280},
        "Sep": {"high": 31, "low": 25, "rain": 270},
        "Oct": {"high": 31, "low": 25, "rain": 230},
        "Nov": {"high": 30, "low": 25, "rain": 180},
        "Dec": {"high": 30, "low": 24, "rain": 140},
    },
}

EQUATORIAL_SEASON = {
    "peak": ["Apr", "May", "Jun", "Sep", "Oct"],
    "shoulder": ["Mar", "Jul", "Aug", "Nov"],
    "low": ["Jan", "Feb", "Dec"],
    "note": "Near the equator, heat and humidity stay high all year. Slightly drier spells are more comfortable for atoll travel; king tides and storms still shape the calendar.",
    "best": "Apr-Jun, Sep-Oct",
    "weather": {
        "Jan": {"high": 31, "low": 26, "rain": 220},
        "Feb": {"high": 31, "low": 26, "rain": 200},
        "Mar": {"high": 31, "low": 26, "rain": 180},
        "Apr": {"high": 31, "low": 26, "rain": 160},
        "May": {"high": 31, "low": 26, "rain": 150},
        "Jun": {"high": 31, "low": 26, "rain": 150},
        "Jul": {"high": 31, "low": 26, "rain": 170},
        "Aug": {"high": 31, "low": 26, "rain": 160},
        "Sep": {"high": 31, "low": 26, "rain": 140},
        "Oct": {"high": 31, "low": 26, "rain": 150},
        "Nov": {"high": 31, "low": 26, "rain": 180},
        "Dec": {"high": 31, "low": 26, "rain": 210},
    },
}

NORFOLK_SEASON = {
    "peak": ["Nov", "Dec", "Jan", "Feb", "Mar"],
    "shoulder": ["Apr", "Oct"],
    "low": ["Jun", "Jul", "Aug"],
    "note": "Norfolk is mild year-round. Summer is busiest for swimming and walking; winter is cooler, windier, and quieter.",
    "best": "Oct-Apr",
    "weather": {
        "Jan": {"high": 25, "low": 19, "rain": 90},
        "Feb": {"high": 25, "low": 19, "rain": 100},
        "Mar": {"high": 24, "low": 18, "rain": 110},
        "Apr": {"high": 22, "low": 17, "rain": 120},
        "May": {"high": 20, "low": 15, "rain": 130},
        "Jun": {"high": 18, "low": 13, "rain": 140},
        "Jul": {"high": 17, "low": 12, "rain": 140},
        "Aug": {"high": 17, "low": 12, "rain": 120},
        "Sep": {"high": 18, "low": 13, "rain": 100},
        "Oct": {"high": 20, "low": 14, "rain": 90},
        "Nov": {"high": 22, "low": 16, "rain": 80},
        "Dec": {"high": 24, "low": 18, "rain": 80},
    },
}


def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "item"


def bbox_from_point(lat: float, lng: float, km: float) -> tuple[float, float, float, float]:
    dlat = km / 111.0
    dlng = km / (111.0 * max(0.35, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def flatten_hike_points(raw) -> list[list[float]]:
    if isinstance(raw, dict):
        if raw.get("type") == "LineString":
            return [list(pt) for pt in (raw.get("coordinates") or []) if len(pt) >= 2]
        if raw.get("type") == "MultiLineString":
            points = []
            for chain in raw.get("coordinates") or []:
                points.extend(list(pt) for pt in chain if len(pt) >= 2)
            return points
        return []
    return [list(pt) for pt in (raw or []) if isinstance(pt, (list, tuple)) and len(pt) >= 2]


def hike_geometry_payload(raw) -> tuple[list[list[float]], dict]:
    if isinstance(raw, dict) and raw.get("type") in {"LineString", "MultiLineString"}:
        points = flatten_hike_points(raw)
        if raw.get("type") == "MultiLineString":
            chains = [c for c in (raw.get("coordinates") or []) if c and len(c) >= 2]
            line = max(chains, key=len) if chains else points
            return line, raw
        return points, raw
    coords = flatten_hike_points(raw)
    return coords, {"type": "LineString", "coordinates": coords}


def bbox_from_coords(coords: list[list[float]]) -> tuple[float, float, float, float]:
    lngs = [float(pt[0]) for pt in coords]
    lats = [float(pt[1]) for pt in coords]
    return min(lngs), min(lats), max(lngs), max(lats)


def centroid_from_coords(coords: list[list[float]]) -> tuple[float, float]:
    lng = sum(float(pt[0]) for pt in coords) / len(coords)
    lat = sum(float(pt[1]) for pt in coords) / len(coords)
    return lng, lat


def update_manifest(path: Path, region_entry: dict) -> None:
    manifest = read_json(path, {})
    regions = [r for r in manifest.get("regions", []) if r.get("id") != REGION_ID]
    regions.append(region_entry)
    manifest["regions"] = regions
    write_json(path, manifest)


def count_region(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE region_id = ?", (REGION_ID,)).fetchone()[0])


def seed_cities(seed: dict) -> None:
    CITIES_OUT_DIR.mkdir(parents=True, exist_ok=True)

    features = []
    details = {}
    for row in seed["cities"]:
        props = {
            "id": row["id"],
            "name": row["name"],
            "country": row["country"],
            "cc": row["cc"],
            "pop": row.get("pop", 0),
            "tier": row.get("tier", "town"),
            "category": row.get("category", ""),
            "locale": row.get("locale", ""),
            "tagline": row.get("tagline", ""),
            "enriched": 1,
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lng"], row["lat"]]},
                "properties": props,
            }
        )
        details[row["id"]] = {
            **props,
            "lat": row["lat"],
            "lng": row["lng"],
            "general": row.get("general", ""),
            "stay": row.get("stay", ""),
            "itinerary": row.get("itinerary", ""),
            "activities": row.get("activities", []),
            "tips": row.get("tips", []),
            "photos": row.get("photos", []),
            "highlights": row.get("highlights", []),
            "source": "curated",
        }

    write_json(CITIES_OUT_DIR / "cities.geojson", {"type": "FeatureCollection", "features": features})
    write_json(CITIES_OUT_DIR / "details.json", details)

    conn = sqlite3.connect(CITIES_DB)
    conn.execute("INSERT OR REPLACE INTO regions (id, label, city_count) VALUES (?, ?, ?)", (REGION_ID, REGION_LABEL, len(seed["cities"])))
    insert = """
        INSERT INTO cities (
            id, region_id, name, country, cc, lat, lng, pop, tier, source,
            general, tagline, stay, itinerary,
            activities_json, tips_json, photos_json, highlights_json, enriched, updated_at,
            category, locale
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            region_id=excluded.region_id,
            name=excluded.name,
            country=excluded.country,
            cc=excluded.cc,
            lat=excluded.lat,
            lng=excluded.lng,
            pop=excluded.pop,
            tier=excluded.tier,
            source=excluded.source,
            general=excluded.general,
            tagline=excluded.tagline,
            stay=excluded.stay,
            itinerary=excluded.itinerary,
            activities_json=excluded.activities_json,
            tips_json=excluded.tips_json,
            photos_json=excluded.photos_json,
            highlights_json=excluded.highlights_json,
            enriched=excluded.enriched,
            updated_at=excluded.updated_at,
            category=excluded.category,
            locale=excluded.locale
    """
    for row in seed["cities"]:
        conn.execute(
            insert,
            (
                row["id"],
                REGION_ID,
                row["name"],
                row["country"],
                row["cc"],
                row["lat"],
                row["lng"],
                row.get("pop", 0),
                row.get("tier", "town"),
                "curated",
                row.get("general", ""),
                row.get("tagline", ""),
                row.get("stay", ""),
                row.get("itinerary", ""),
                json.dumps(row.get("activities", []), ensure_ascii=False),
                json.dumps(row.get("tips", []), ensure_ascii=False),
                json.dumps(row.get("photos", []), ensure_ascii=False),
                json.dumps(row.get("highlights", []), ensure_ascii=False),
                1,
                NOW_ISO,
                row.get("category", ""),
                row.get("locale", ""),
            ),
        )
    count = count_region(conn, "cities")
    conn.execute("UPDATE regions SET city_count = ? WHERE id = ?", (count, REGION_ID))
    conn.commit()
    conn.close()

    update_manifest(
        CITIES_MANIFEST,
        {
            "id": REGION_ID,
            "label": REGION_LABEL,
            "count": count,
            "legacyGeojson": "./Trip/cities/oceania/cities.geojson",
        },
    )


def seed_parks(seed: dict) -> None:
    conn = sqlite3.connect(PARKS_DB)
    conn.execute("INSERT OR REPLACE INTO regions (id, label, park_count) VALUES (?, ?, ?)", (REGION_ID, REGION_LABEL, len(seed["parks"])))
    insert = """
        INSERT INTO parks (
            id, region_id, osm_id, name, country, cc, lat, lng, area_km2, biodiversity,
            popularity, tier, west, south, east, north,
            summary, tagline, stay, activities_json, tips_json, photos_json, highlights_json,
            iucn_category, source, enriched, updated_at, category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            region_id=excluded.region_id,
            name=excluded.name,
            country=excluded.country,
            cc=excluded.cc,
            lat=excluded.lat,
            lng=excluded.lng,
            area_km2=excluded.area_km2,
            biodiversity=excluded.biodiversity,
            popularity=excluded.popularity,
            tier=excluded.tier,
            west=excluded.west,
            south=excluded.south,
            east=excluded.east,
            north=excluded.north,
            summary=excluded.summary,
            tagline=excluded.tagline,
            stay=excluded.stay,
            activities_json=excluded.activities_json,
            tips_json=excluded.tips_json,
            photos_json=excluded.photos_json,
            highlights_json=excluded.highlights_json,
            source=excluded.source,
            enriched=excluded.enriched,
            updated_at=excluded.updated_at,
            category=excluded.category
    """
    for row in seed["parks"]:
        area = float(row.get("area_km2") or 50)
        pop = int(row.get("popularity") or 70)
        tier = "major" if pop >= 92 or area >= 800 else "regional" if pop >= 75 or area >= 100 else "local"
        west, south, east, north = bbox_from_point(row["lat"], row["lng"], km=min(120, max(12, math.sqrt(area) * 2.4)))
        conn.execute(
            insert,
            (
                slugify(f"{row['name']}-{row['country']}"),
                REGION_ID,
                row.get("osm_id"),
                row["name"],
                row["country"],
                row["cc"].lower(),
                row["lat"],
                row["lng"],
                area,
                int(row.get("biodiversity") or 3),
                pop,
                tier,
                west,
                south,
                east,
                north,
                row.get("summary"),
                row.get("tagline"),
                row.get("stay", "1-2 days"),
                json.dumps(row.get("activities", []), ensure_ascii=False),
                json.dumps(row.get("tips", []), ensure_ascii=False),
                json.dumps(row.get("photos", []), ensure_ascii=False),
                json.dumps(row.get("highlights", []), ensure_ascii=False),
                row.get("iucn_category", "II"),
                "curated",
                1,
                NOW_ISO,
                row.get("category", "national-park"),
            ),
        )
    count = count_region(conn, "parks")
    conn.execute("UPDATE regions SET park_count = ? WHERE id = ?", (count, REGION_ID))
    conn.commit()
    conn.close()
    update_manifest(PARKS_MANIFEST, {"id": REGION_ID, "label": REGION_LABEL, "count": count})


def seed_pois(seed: dict) -> None:
    conn = sqlite3.connect(POI_DB)
    conn.execute("INSERT OR REPLACE INTO regions (id, label, poi_count) VALUES (?, ?, ?)", (REGION_ID, REGION_LABEL, len(seed["pois"])))
    insert = """
        INSERT INTO pois (
            id, region_id, osm_id, name, country, cc, category, lat, lng,
            popularity, tier, west, south, east, north,
            summary, tagline, activities_json, tips_json, photos_json, highlights_json,
            source, enriched, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            region_id=excluded.region_id,
            name=excluded.name,
            country=excluded.country,
            cc=excluded.cc,
            category=excluded.category,
            lat=excluded.lat,
            lng=excluded.lng,
            popularity=excluded.popularity,
            tier=excluded.tier,
            west=excluded.west,
            south=excluded.south,
            east=excluded.east,
            north=excluded.north,
            summary=excluded.summary,
            tagline=excluded.tagline,
            activities_json=excluded.activities_json,
            tips_json=excluded.tips_json,
            photos_json=excluded.photos_json,
            highlights_json=excluded.highlights_json,
            source=excluded.source,
            enriched=excluded.enriched,
            updated_at=excluded.updated_at
    """
    for row in seed["pois"]:
        pop = int(row.get("popularity") or 70)
        tier = "major" if pop >= 92 else "regional" if pop >= 78 else "local"
        west, south, east, north = bbox_from_point(row["lat"], row["lng"], km=8)
        tagline = row.get("tagline") or f"Explore {row['name']}"
        conn.execute(
            insert,
            (
                slugify(f"{row['name']}-{row['country']}"),
                REGION_ID,
                row.get("osm_id"),
                row["name"],
                row["country"],
                row["cc"].lower(),
                row.get("category", "landmark"),
                row["lat"],
                row["lng"],
                pop,
                tier,
                west,
                south,
                east,
                north,
                row.get("summary") or tagline,
                tagline,
                json.dumps(row.get("activities", []), ensure_ascii=False),
                json.dumps(row.get("tips", []), ensure_ascii=False),
                json.dumps(row.get("photos", []), ensure_ascii=False),
                json.dumps(row.get("highlights", []), ensure_ascii=False),
                "curated",
                1,
                NOW_ISO,
            ),
        )
    count = count_region(conn, "pois")
    conn.execute("UPDATE regions SET poi_count = ? WHERE id = ?", (count, REGION_ID))
    conn.commit()
    conn.close()
    update_manifest(POI_MANIFEST, {"id": REGION_ID, "label": REGION_LABEL, "count": count})


def seed_hikes(seed: dict) -> None:
    features = []
    conn = sqlite3.connect(HIKES_DB)
    conn.execute("INSERT OR REPLACE INTO regions (id, label, hike_count) VALUES (?, ?, ?)", (REGION_ID, REGION_LABEL, len(seed["hikes"])))
    insert = """
        INSERT INTO hikes (
            id, region_id, osm_id, name, country, cc, lat, lng,
            length_km, ascent_m, difficulty, network, route_type,
            popularity, tier, west, south, east, north,
            summary, tagline, tips_json, photos_json, geometry_json, source, enriched,
            start_lat, start_lng, end_lat, end_lng,
            start_name, end_name, start_instructions, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            region_id=excluded.region_id,
            name=excluded.name,
            country=excluded.country,
            cc=excluded.cc,
            lat=excluded.lat,
            lng=excluded.lng,
            length_km=excluded.length_km,
            ascent_m=excluded.ascent_m,
            difficulty=excluded.difficulty,
            network=excluded.network,
            route_type=excluded.route_type,
            popularity=excluded.popularity,
            tier=excluded.tier,
            west=excluded.west,
            south=excluded.south,
            east=excluded.east,
            north=excluded.north,
            summary=excluded.summary,
            tagline=excluded.tagline,
            tips_json=excluded.tips_json,
            photos_json=excluded.photos_json,
            geometry_json=excluded.geometry_json,
            source=excluded.source,
            enriched=excluded.enriched,
            start_lat=excluded.start_lat,
            start_lng=excluded.start_lng,
            end_lat=excluded.end_lat,
            end_lng=excluded.end_lng,
            start_name=excluded.start_name,
            end_name=excluded.end_name,
            start_instructions=excluded.start_instructions,
            updated_at=excluded.updated_at
    """
    for row in seed["hikes"]:
        coords, geometry = hike_geometry_payload(row["geometry"])
        if len(coords) < 2:
            raise ValueError(f"Hike {row.get('id') or row.get('name')} is missing usable geometry")
        all_points = flatten_hike_points(geometry) or coords
        west, south, east, north = bbox_from_coords(all_points)
        lng, lat = centroid_from_coords(all_points)
        start_lng, start_lat = coords[0]
        end_lng, end_lat = coords[-1]
        conn.execute(
            insert,
            (
                row["id"],
                REGION_ID,
                row.get("osm_id"),
                row["name"],
                row["country"],
                row["cc"].lower(),
                lat,
                lng,
                row.get("length_km"),
                row.get("ascent_m"),
                row.get("difficulty"),
                row.get("network", ""),
                row.get("route_type", "hiking"),
                int(row.get("popularity") or 70),
                row.get("tier", "regional"),
                west,
                south,
                east,
                north,
                row.get("summary"),
                row.get("tagline"),
                json.dumps(row.get("tips", []), ensure_ascii=False),
                json.dumps(row.get("photos", []), ensure_ascii=False),
                json.dumps(geometry, ensure_ascii=False),
                "curated",
                1,
                start_lat,
                start_lng,
                end_lat,
                end_lng,
                row.get("start_name"),
                row.get("end_name"),
                row.get("start_instructions"),
                NOW_ISO,
            ),
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "id": row["id"],
                    "name": row["name"],
                    "country": row["country"],
                    "cc": row["cc"].lower(),
                    "length_km": row.get("length_km"),
                    "popularity": int(row.get("popularity") or 70),
                    "tier": row.get("tier", "regional"),
                    "tagline": row.get("tagline"),
                },
            }
        )
    count = count_region(conn, "hikes")
    conn.execute("UPDATE regions SET hike_count = ? WHERE id = ?", (count, REGION_ID))
    conn.commit()
    conn.close()

    HIKES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(HIKES_OUT_DIR / "hikes-index.geojson", {"type": "FeatureCollection", "features": features})
    update_manifest(
        HIKES_MANIFEST,
        {
            "id": REGION_ID,
            "label": REGION_LABEL,
            "count": count,
            "legacyGeojson": "./Trip/hikes/oceania/hikes-index.geojson",
        },
    )


def seed_auxiliary_files() -> None:
    if not REGION_GEOJSON.is_file():
        write_json(REGION_GEOJSON, OCEANIA_COUNTRY_GEOJSON)

    populations = read_json(COUNTRY_POPULATIONS, {"schemaVersion": 1, "populations": {}})
    populations.setdefault("populations", {})
    oceania_populations = {
        "AU": 26700000,
        "NZ": 5200000,
        "FJ": 930000,
        "PG": 10300000,
        "SB": 750000,
        "VU": 330000,
        "NC": 290000,
        "PF": 280000,
        "WS": 220000,
        "AS": 44000,
        "TO": 105000,
        "CK": 15000,
        "NU": 1800,
        "PW": 18000,
        "GU": 170000,
        "MP": 47000,
        "FM": 115000,
        "MH": 42000,
        "KI": 130000,
        "NR": 12000,
        "TV": 11000,
        "WF": 11500,
        "NF": 2200,
    }
    if any(populations["populations"].get(cc) != value for cc, value in oceania_populations.items()):
        populations["populations"].update(oceania_populations)
        write_json(COUNTRY_POPULATIONS, populations)

    tips = read_json(COUNTRY_TIPS, {})
    tips_payload = {
        "Australia": [
            "Distances are large \u2014 plan fuel, water, and rest stops carefully",
            "Sun protection is essential in every season",
            "Swim only between the flags on surf beaches",
            "Remote and Aboriginal-managed areas may require permits",
        ],
        "New Zealand": [
            "Book Great Walk huts and campsites as early as possible",
            "Weather can change quickly in alpine areas",
            "Carry insect repellent for sandflies on the west coast and fiords",
            "Allow buffer time for ferry crossings and mountain roads",
        ],
        "Fiji": [
            "Village visits usually need a sevusevu or local invitation",
            "Cover shoulders and knees at temples and in villages",
            "Cyclone season runs roughly November to April",
            "Island transfers fill on weekends — book boats and flights",
        ],
        "Papua New Guinea": [
            "Use trusted transport and local advice, especially after dark",
            "Highland nights are cold even when the coast is hot",
            "Mosquito protection is essential in lowland and river country",
            "Cultural shows and flights book out — plan ahead",
        ],
        "Vanuatu": [
            "Reef shoes help on coral beaches",
            "Volcano visits are guided — respect exclusion zones",
            "Cash is useful outside Port Vila",
            "Sunday is quiet on many islands",
        ],
        "Solomon Islands": [
            "Boats and weather set the day's plan more than clocks",
            "Cash is more useful than cards outside Honiara",
            "Ask before photographing people or custom sites",
            "WWII sites are spread out — a local driver helps",
        ],
        "New Caledonia": [
            "Sunday services are limited outside Nouméa",
            "Ask before entering tribal land on the east coast",
            "Lagoon sun is intense even on breezy days",
            "A car is the practical way to see Grande Terre",
        ],
        "French Polynesia": [
            "Inter-island flights are the usual hop — book early",
            "Sunday is quiet in towns and villages",
            "Pearl and market prices vary — compare before buying",
            "Mountain valleys can require a municipal permit",
        ],
        "Samoa": [
            "Sunday is a rest day in villages — plan meals and travel",
            "Cover knees at churches and when visiting villages",
            "A car or 4WD is essential on Savai'i",
            "Lava-hot sun — carry water on short walks",
        ],
        "American Samoa": [
            "Sunday village rules apply",
            "The harbour is often rainy and humid",
            "National-park ridges get muddy — wear grip",
            "Honolulu flights set the busy days",
        ],
        "Tonga": [
            "Sunday is strictly observed on Tongatapu",
            "Dress modestly in towns and villages",
            "Whale trips are seasonal and based in Vava'u",
            "Ferries to outer islands can cancel in wind",
        ],
        "Cook Islands": [
            "Sunday is quiet on Rarotonga and Aitutaki",
            "The circle-island bus is the easy way around Rarotonga",
            "Scooters need care on wet inland roads",
            "Book Aitutaki flights and lagoon cruises ahead",
        ],
        "Niue": [
            "Hire a car on arrival — there is no public bus",
            "Reef entries can be sharp — reef shoes help",
            "Shops close early and on Sunday",
            "Sea tracks are safest at lower swell",
        ],
        "Palau": [
            "Rock Islands boats and Jellyfish Lake permits sell out",
            "The visitor fee is paid on arrival — keep the receipt",
            "Sun and glare on the water are intense",
            "A hire car is needed for Babeldaob",
        ],
        "Guam": [
            "Heat and humidity are high — start walks early",
            "Typhoon season can close northern parks",
            "A rental car makes the island easy in a day",
            "Reef sun is stronger than it feels in the wind",
        ],
        "Northern Mariana Islands": [
            "A car is the practical way around Saipan",
            "Cliff memorials are sobering — visit quietly",
            "Midday heat is strong on exposed lookouts",
            "Some north-island roads are narrow",
        ],
        "Federated States of Micronesia": [
            "Rain is frequent on Pohnpei — trails get slick",
            "Nan Madol access depends on tide and a boat",
            "Cash is useful outside Kolonia",
            "Chuuk wreck dives are advanced and need booking",
        ],
        "Marshall Islands": [
            "The road is the island — allow time for Laura",
            "Sun and lagoon glare are intense",
            "Supplies thin toward the west end of Majuro",
            "Fresh water is limited — refill when you can",
        ],
        "Kiribati": [
            "The South Tarawa causeway is busy and hot",
            "Ask before photographing people or maneaba",
            "Fresh water is limited",
            "Kiritimati flights are infrequent — build slack",
        ],
        "Nauru": [
            "A car or scooter covers the island loop in a day",
            "Visitor facilities are limited — carry water and cash",
            "Heat on the plateau is intense",
            "Ask before entering district land",
        ],
        "Tuvalu": [
            "Flights are few — confirm the schedule twice",
            "King tides can flood low paths",
            "Cash and patience are essential",
            "The airstrip is also the evening park",
        ],
        "Wallis and Futuna": [
            "Flights via Nouméa or Nadi are limited",
            "Sunday is quiet",
            "A car is the easy way around Uvea",
            "Ask before entering customary land",
        ],
        "Norfolk Island": [
            "Flights are limited — hire a car on arrival",
            "Wind is strong on the southern lawns",
            "Many sites close on Sunday",
            "Drive on the left and watch for cattle",
        ],
    }
    if any(tips.get(country) != values for country, values in tips_payload.items()):
        tips.update(tips_payload)
        write_json(COUNTRY_TIPS, tips)

    seasons = read_json(COUNTRY_SEASONS, {"default": None, "byCountry": {}})
    seasons.setdefault("byCountry", {})
    season_payload = {
        "Australia": AUSTRALIA_SEASON,
        "New Zealand": NEW_ZEALAND_SEASON,
        "Fiji": SOUTH_PACIFIC_DRY_SEASON,
        "Papua New Guinea": PNG_SEASON,
        "Vanuatu": SOUTH_PACIFIC_DRY_SEASON,
        "Solomon Islands": SOUTH_PACIFIC_DRY_SEASON,
        "New Caledonia": SOUTH_PACIFIC_DRY_SEASON,
        "French Polynesia": SOUTH_PACIFIC_DRY_SEASON,
        "Samoa": SOUTH_PACIFIC_DRY_SEASON,
        "American Samoa": SOUTH_PACIFIC_DRY_SEASON,
        "Tonga": SOUTH_PACIFIC_DRY_SEASON,
        "Cook Islands": SOUTH_PACIFIC_DRY_SEASON,
        "Niue": SOUTH_PACIFIC_DRY_SEASON,
        "Palau": NORTH_PACIFIC_DRY_SEASON,
        "Guam": NORTH_PACIFIC_DRY_SEASON,
        "Northern Mariana Islands": NORTH_PACIFIC_DRY_SEASON,
        "Federated States of Micronesia": NORTH_PACIFIC_DRY_SEASON,
        "Marshall Islands": NORTH_PACIFIC_DRY_SEASON,
        "Kiribati": EQUATORIAL_SEASON,
        "Nauru": EQUATORIAL_SEASON,
        "Tuvalu": EQUATORIAL_SEASON,
        "Wallis and Futuna": SOUTH_PACIFIC_DRY_SEASON,
        "Norfolk Island": NORFOLK_SEASON,
    }
    if any(seasons["byCountry"].get(country) != values for country, values in season_payload.items()):
        seasons["byCountry"].update(season_payload)
        write_json(COUNTRY_SEASONS, seasons)


def main() -> None:
    seed = read_json(SEED_PATH, None)
    if not seed:
        raise SystemExit(f"Missing {SEED_PATH}")
    seed_auxiliary_files()
    seed_cities(seed)
    seed_parks(seed)
    seed_pois(seed)
    seed_hikes(seed)
    print(
        f"Seeded {REGION_LABEL}: "
        f"{len(seed['cities'])} cities, {len(seed['parks'])} parks, "
        f"{len(seed['pois'])} POIs, {len(seed['hikes'])} hikes"
    )


if __name__ == "__main__":
    main()
