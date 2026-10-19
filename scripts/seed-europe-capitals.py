#!/usr/bin/env python3
"""Ensure every European capital exists, is classified, and is map-visible.

Adds the three microstate capitals missing from GeoNames (Vaduz, San Marino,
Vatican City), promotes all European capitals to `category=capital` /
`tier=major`, and mirrors those roster changes into the Europe seed JSON,
GeoJSON, details index, and cities manifest.

Does not fetch Wikipedia copy — run afterwards:

    python scripts/classify-places.py --apply
    python scripts/enrich-cities-db.py --capitals --photos auto --workers 8 --progress
    python scripts/sync-city-details.py --region europe --enriched-only
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog_paths import CITIES_DB  # noqa: E402
from place_categories import (  # noqa: E402
    CAPITALS_BY_CC,
    classify_city,
    is_capital_name,
)

OCEANIA_CC = {
    "FJ", "PG", "SB", "VU", "NC", "PF", "WS", "AS", "TO", "CK", "NU",
    "PW", "GU", "MP", "FM", "MH", "KI", "NR", "TV", "WF", "NF",
}

SEED_PATH = ROOT / "scripts" / "data" / "europe-cities-seed.json"
GEOJSON_PATH = ROOT / "Trip" / "cities" / "europe" / "cities.geojson"
DETAILS_PATH = ROOT / "Trip" / "cities" / "europe" / "details.json"
MANIFEST_PATH = ROOT / "Trip" / "cities" / "manifest.json"
NOW_ISO = datetime.now(timezone.utc).isoformat()

MISSING_CAPITALS = [
    {
        "id": "vaduz-li",
        "name": "Vaduz",
        "country": "Liechtenstein",
        "cc": "LI",
        "lat": 47.1410,
        "lng": 9.5215,
        "pop": 5741,
        "tier": "major",
        "category": "capital",
        "locale": "mountain",
        "source": "curated",
    },
    {
        "id": "san-marino-sm",
        "name": "San Marino",
        "country": "San Marino",
        "cc": "SM",
        "lat": 43.9367,
        "lng": 12.4467,
        "pop": 4127,
        "tier": "major",
        "category": "capital",
        "locale": "mountain",
        "source": "curated",
    },
    {
        "id": "vatican-city-va",
        "name": "Vatican City",
        "country": "Vatican City",
        "cc": "VA",
        "lat": 41.9029,
        "lng": 12.4534,
        "pop": 825,
        "tier": "major",
        "category": "capital",
        "locale": "inland",
        "source": "curated",
    },
]


def open_writable(primary: Path) -> tuple[sqlite3.Connection, Path]:
    try:
        conn = sqlite3.connect(str(primary))
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        return conn, primary
    except sqlite3.OperationalError:
        new_path = Path(f"{primary}.new")
        shutil.copyfile(primary, new_path)
        conn = sqlite3.connect(str(new_path))
        return conn, new_path


def stub_detail(row: dict) -> dict:
    name = row["name"]
    country = row["country"]
    return {
        "id": row["id"],
        "name": name,
        "country": country,
        "cc": row["cc"],
        "lat": row["lat"],
        "lng": row["lng"],
        "pop": row["pop"],
        "tier": row["tier"],
        "category": row.get("category", "capital"),
        "locale": row.get("locale", "inland"),
        "general": f"{name} is a destination in {country} — open for a future deep-dive story card.",
        "activities": ["Old town walk", "Local food market", "Viewpoint sunset"],
        "tips": [
            "Check seasonal opening hours for major sights",
            "Book accommodation early in peak season",
        ],
        "tagline": f"Discover {name}",
        "photos": [],
        "highlights": [],
        "source": row.get("source", "curated"),
    }


def insert_missing(conn: sqlite3.Connection) -> dict:
    added = 0
    skipped = 0
    for row in MISSING_CAPITALS:
        exists = conn.execute("SELECT 1 FROM cities WHERE id = ?", (row["id"],)).fetchone()
        if exists:
            skipped += 1
            continue
        conn.execute(
            """
            INSERT INTO cities (
                id, region_id, name, country, cc, lat, lng, pop, tier, source,
                general, tagline, activities_json, tips_json, photos_json,
                highlights_json, enriched, updated_at, category, locale
            ) VALUES (
                ?, 'europe', ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, '[]', '[]', '[]', '[]', 0, ?, ?, ?
            )
            """,
            (
                row["id"], row["name"], row["country"], row["cc"],
                row["lat"], row["lng"], row["pop"], row["tier"], row["source"],
                stub_detail(row)["general"], stub_detail(row)["tagline"],
                NOW_ISO, row["category"], row["locale"],
            ),
        )
        added += 1
    return {"added": added, "skipped": skipped}


def promote_capitals(conn: sqlite3.Connection) -> dict:
    europe_ccs = [cc for cc in CAPITALS_BY_CC if cc not in OCEANIA_CC]
    rows = conn.execute(
        f"SELECT id, name, cc, pop, lat, lng, tier, category, locale FROM cities "
        f"WHERE region_id = 'europe' AND cc IN ({','.join('?' * len(europe_ccs))})",
        europe_ccs,
    ).fetchall()
    promoted = 0
    classified = 0
    for cid, name, cc, pop, lat, lng, tier, category, locale in rows:
        if not is_capital_name(name, cc):
            continue
        new_cat, new_loc = classify_city(name=name, cc=cc, pop=pop, lat=lat, lng=lng)
        new_tier = "major"
        if category == new_cat and locale == new_loc and tier == new_tier:
            continue
        conn.execute(
            "UPDATE cities SET category = ?, locale = ?, tier = ?, updated_at = ? WHERE id = ?",
            (new_cat, new_loc, new_tier, NOW_ISO, cid),
        )
        classified += 1
        if tier != new_tier:
            promoted += 1
    return {"classified": classified, "promoted": promoted}


def bump_region_count(conn: sqlite3.Connection) -> int:
    count = conn.execute(
        "SELECT COUNT(*) FROM cities WHERE region_id = 'europe'"
    ).fetchone()[0]
    conn.execute(
        "UPDATE regions SET city_count = ? WHERE id = 'europe'",
        (count,),
    )
    return count


def update_seed_json() -> dict:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    by_key = {(row.get("cc"), (row.get("name") or "").lower()): row for row in seed}
    added = 0
    for row in MISSING_CAPITALS:
        key = (row["cc"], row["name"].lower())
        if key in by_key:
            continue
        seed.append({
            "name": row["name"],
            "country": row["country"],
            "cc": row["cc"],
            "lat": row["lat"],
            "lng": row["lng"],
            "pop": row["pop"],
            "tier": "major",
        })
        added += 1
    if added:
        SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"added": added}


def update_geojson() -> dict:
    data = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    features = data.setdefault("features", [])
    by_id = {(f.get("properties") or {}).get("id"): f for f in features}
    added = 0
    updated = 0
    for row in MISSING_CAPITALS:
        existing = by_id.get(row["id"])
        if existing:
            props = existing.setdefault("properties", {})
            props["tier"] = "major"
            props["category"] = "capital"
            props["pop"] = row["pop"]
            existing["geometry"] = {"type": "Point", "coordinates": [row["lng"], row["lat"]]}
            updated += 1
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "id": row["id"],
                "name": row["name"],
                "country": row["country"],
                "cc": row["cc"],
                "pop": row["pop"],
                "tier": "major",
                "category": "capital",
            },
            "geometry": {"type": "Point", "coordinates": [row["lng"], row["lat"]]},
        })
        added += 1
    # Promote existing capital features already in the file
    for feature in features:
        props = feature.get("properties") or {}
        if is_capital_name(props.get("name") or "", props.get("cc")):
            if props.get("tier") != "major":
                props["tier"] = "major"
                updated += 1
            props["category"] = "capital"
    GEOJSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {"added": added, "updated": updated}


def update_details_stubs() -> dict:
    details = json.loads(DETAILS_PATH.read_text(encoding="utf-8"))
    added = 0
    for row in MISSING_CAPITALS:
        if row["id"] in details:
            continue
        details[row["id"]] = stub_detail(row)
        added += 1
    if added:
        DETAILS_PATH.write_text(
            json.dumps(details, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {"added": added}


def update_manifest(count: int) -> None:
    if not MANIFEST_PATH.is_file():
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for region in manifest.get("regions") or []:
        if region.get("id") == "europe":
            region["count"] = count
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    conn, used = open_writable(CITIES_DB)
    try:
        missing = insert_missing(conn)
        promoted = promote_capitals(conn)
        count = bump_region_count(conn)
        conn.commit()
    finally:
        conn.close()

    seed = update_seed_json()
    geo = update_geojson()
    details = update_details_stubs()
    update_manifest(count)

    print(f"cities.db ({used.name}): +{missing['added']} capitals, {missing['skipped']} already present")
    print(f"  classified/promoted {promoted['classified']} capitals ({promoted['promoted']} tier->major)")
    print(f"  europe city_count={count}")
    print(f"seed json: +{seed['added']}")
    print(f"geojson: +{geo['added']} features, {geo['updated']} updated")
    print(f"details: +{details['added']} stubs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
