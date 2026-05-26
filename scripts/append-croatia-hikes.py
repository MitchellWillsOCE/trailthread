#!/usr/bin/env python3
"""Fetch and append Croatia/Adriatic hike seeds into hikes.db without a full rebuild."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location("build_hikes", ROOT / "scripts" / "build-hikes-db.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

SEED_PATH = ROOT / "scripts" / "data" / "croatia-adriatic-hikes-seed.json"
DB_PATH = ROOT / "Trip" / "hikes" / "hikes.db"


def main() -> None:
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = {row[0] for row in conn.execute("SELECT id FROM hikes")}
    added = 0

    for seed in seeds:
        hike_id = f"europe-{int(seed['osm_id'])}"
        if hike_id in existing:
            print(f"skip {hike_id}")
            continue
        osm_id = int(seed["osm_id"])
        print(f"fetch {osm_id} {seed.get('name', '')}")
        payload = build.fetch_relation(osm_id)
        time.sleep(0.8)
        if not payload:
            print(f"  failed {osm_id}")
            continue
        record = build.build_hike_record(
            osm_id=osm_id,
            name=seed.get("name") or payload["tags"].get("name") or f"Trail {osm_id}",
            country=seed.get("country", "Europe"),
            cc=seed.get("cc", ""),
            coords=payload["coordinates"],
            tags=payload["tags"],
            seed_popularity=int(seed.get("popularity", 85)),
        )
        if not record:
            print(f"  no record {osm_id}")
            continue
        conn.execute(
            """
            INSERT INTO hikes (
              id, region_id, osm_id, name, country, cc, lat, lng, length_km,
              ascent_m, difficulty, network, route_type, popularity, tier,
              west, south, east, north, summary, tagline, tips_json, photos_json,
              geometry_json, source, enriched, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record["id"],
                record["region_id"],
                record["osm_id"],
                record["name"],
                record["country"],
                record["cc"],
                record["lat"],
                record["lng"],
                record["length_km"],
                record.get("ascent_m"),
                record.get("difficulty"),
                record.get("network"),
                record.get("route_type"),
                record["popularity"],
                record["tier"],
                record["west"],
                record["south"],
                record["east"],
                record["north"],
                record.get("summary"),
                record.get("tagline"),
                record["tips_json"],
                record["photos_json"],
                record["geometry_json"],
                record.get("source", "OpenStreetMap"),
                0,
                record.get("updated_at"),
            ),
        )
        existing.add(hike_id)
        added += 1
        print(f"  + {hike_id} ({record['length_km']} km)")

    count = conn.execute("SELECT COUNT(*) FROM hikes").fetchone()[0]
    conn.execute(
        "UPDATE regions SET hike_count = ? WHERE id = 'europe'",
        (count,),
    )
    conn.commit()
    rows = [dict(r) for r in conn.execute("SELECT * FROM hikes")]
    conn.close()
    build.write_legacy_geojson(rows)
    manifest = json.loads((ROOT / "Trip" / "hikes" / "manifest.json").read_text(encoding="utf-8"))
    for region in manifest.get("regions", []):
        if region.get("id") == "europe":
            region["count"] = count
    (ROOT / "Trip" / "hikes" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Added {added} trails; europe count now {count}")


if __name__ == "__main__":
    main()
