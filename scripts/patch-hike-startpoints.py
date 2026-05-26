#!/usr/bin/env python3
"""
Surgically update hikes.db without a full rebuild:

  1. Adds the start/end columns to the schema if missing (idempotent).
  2. For trails whose seed osm_id has changed since the DB was built,
     re-fetches the relation, replaces geometry/length/bbox, and writes start/end fields.
  3. For all other trails, fills start/end coordinates from the existing geometry and
     fetches OSM tags (from/to/operator/website/network) to write start_name/end_name
     and start_instructions.

Run after every seed correction batch instead of nuking the whole DB.

Usage:
  python scripts/patch-hike-startpoints.py                # patch all trails
  python scripts/patch-hike-startpoints.py --only "Pennine Way"
  python scripts/patch-hike-startpoints.py --skip-tags    # only populate lat/lng from geometry
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "Trip" / "hikes" / "hikes.db"
SEED_PATH = ROOT / "scripts" / "data" / "europe-hikes-seed.json"
MONTENEGRO_SEED_PATH = ROOT / "scripts" / "data" / "montenegro-hikes-seed.json"
CROATIA_SEED_PATH = ROOT / "scripts" / "data" / "croatia-adriatic-hikes-seed.json"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

spec = importlib.util.spec_from_file_location(
    "build_hikes_db", ROOT / "scripts" / "build-hikes-db.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def safe(t: str) -> str:
    return str(t).encode("ascii", "replace").decode("ascii")


COLUMNS_TO_ADD = [
    ("start_lat", "REAL"),
    ("start_lng", "REAL"),
    ("end_lat", "REAL"),
    ("end_lng", "REAL"),
    ("start_name", "TEXT"),
    ("end_name", "TEXT"),
    ("start_instructions", "TEXT"),
]


def ensure_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(hikes)")
    existing = {row[1] for row in cur.fetchall()}
    for col, sql_type in COLUMNS_TO_ADD:
        if col not in existing:
            conn.execute(f"ALTER TABLE hikes ADD COLUMN {col} {sql_type}")
            print(f"  + added column {col}")
    conn.commit()


def load_seed_index() -> dict[str, dict]:
    by_name: dict[str, dict] = {}
    for path in (SEED_PATH, MONTENEGRO_SEED_PATH, CROATIA_SEED_PATH):
        if not path.is_file():
            continue
        for seed in json.loads(path.read_text(encoding="utf-8")):
            by_name[seed["name"].strip().lower()] = seed
    return by_name


def fetch_tags(osm_id: int) -> dict:
    """Lightweight tags-only Overpass fetch — much faster than full geometry."""
    q = f"[out:json][timeout:60];relation({osm_id});out tags;"
    try:
        data = build.http_post(q)
    except Exception as e:
        print(f"  tags fetch FAIL for {osm_id}: {e}")
        return {}
    rel = next((e for e in data.get("elements", []) if e.get("type") == "relation"), None)
    return (rel or {}).get("tags", {}) if rel else {}


def parse_geometry(raw: str) -> list[list[list[float]]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        if parsed.get("type") == "MultiLineString":
            return [c for c in parsed["coordinates"] if isinstance(c, list) and len(c) >= 2]
        if parsed.get("type") == "LineString" and parsed.get("coordinates"):
            return [parsed["coordinates"]]
        return []
    if isinstance(parsed, list):
        if parsed and isinstance(parsed[0], list) and isinstance(parsed[0][0], (int, float)):
            return [parsed]
        if parsed and isinstance(parsed[0], list) and isinstance(parsed[0][0], list):
            return parsed
    return []


def longest(chains: list[list[list[float]]]) -> list[list[float]]:
    return max(chains, key=build.line_length_km) if chains else []


def fully_rebuild_row(conn: sqlite3.Connection, seed: dict, existing_id: str) -> bool:
    """For trails whose seed osm_id changed since the last build, re-fetch and replace."""
    osm_id = int(seed["osm_id"])
    print(f"  re-fetching {seed['name']} osm={osm_id}…")
    payload = build.fetch_relation(osm_id)
    if not payload:
        print(f"    fetch returned no chains")
        return False
    record = build.build_hike_record(
        osm_id=osm_id,
        name=seed.get("name") or payload["tags"].get("name") or f"Trail {osm_id}",
        country=seed.get("country", "Europe"),
        cc=seed.get("cc", ""),
        chains=payload["chains"],
        tags=payload["tags"],
        seed_popularity=int(seed.get("popularity", 85)),
    )
    if not record:
        print(f"    record build failed (too short?)")
        return False
    # Preserve enrichment fields from existing row
    existing = conn.execute(
        "SELECT summary, tagline, tips_json, photos_json, enriched FROM hikes WHERE id = ?",
        (existing_id,),
    ).fetchone()
    if existing and existing[4]:
        # keep prior enrichment
        record["summary"] = existing[0] or record["summary"]
        record["tagline"] = existing[1] or record["tagline"]
        record["tips_json"] = existing[2] or record["tips_json"]
        record["photos_json"] = existing[3] or record["photos_json"]
        record["enriched"] = existing[4]

    conn.execute("DELETE FROM hikes WHERE id = ?", (existing_id,))
    conn.execute(
        """
        INSERT INTO hikes (
            id, region_id, osm_id, name, country, cc, lat, lng,
            length_km, ascent_m, difficulty, network, route_type,
            popularity, tier, west, south, east, north,
            summary, tagline, tips_json, photos_json, geometry_json, source, enriched,
            start_lat, start_lng, end_lat, end_lng,
            start_name, end_name, start_instructions, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            record["id"], record["region_id"], record["osm_id"], record["name"],
            record["country"], record["cc"], record["lat"], record["lng"],
            record["length_km"], record["ascent_m"], record["difficulty"],
            record["network"], record["route_type"], record["popularity"],
            record["tier"], record["west"], record["south"], record["east"], record["north"],
            record["summary"], record["tagline"], record["tips_json"],
            record["photos_json"], record["geometry_json"], record["source"], record["enriched"],
            record["start_lat"], record["start_lng"], record["end_lat"], record["end_lng"],
            record["start_name"], record["end_name"], record["start_instructions"],
        ),
    )
    print(f"    -> wrote {record['name']} ({record['length_km']:.0f} km, "
          f"{'multi-line' if 'MultiLineString' in record['geometry_json'] else 'line'})")
    return True


def patch_existing_row(conn: sqlite3.Connection, row, *, skip_tags: bool, sleep: float) -> None:
    """For trails whose osm_id hasn't changed, populate start/end from the stored geometry."""
    chains = parse_geometry(row["geometry_json"])
    if not chains:
        return
    chain = longest(chains)
    start_lng, start_lat = chain[0]
    end_lng, end_lat = chain[-1]

    start_name = row["start_name"]
    end_name = row["end_name"]
    start_instructions = row["start_instructions"]
    if not skip_tags and not start_instructions:
        tags = fetch_tags(int(row["osm_id"])) if row["osm_id"] else {}
        time.sleep(sleep)
        from_tag = (tags.get("from") or "").strip() or None
        to_tag = (tags.get("to") or "").strip() or None
        start_name = start_name or from_tag
        end_name = end_name or to_tag
        start_instructions = build._build_start_instructions(
            name=row["name"],
            country=row["country"],
            start_name=start_name,
            end_name=end_name,
            tags=tags,
            length_km=row["length_km"] or 0,
        )

    conn.execute(
        """
        UPDATE hikes
           SET start_lat = ?,
               start_lng = ?,
               end_lat = ?,
               end_lng = ?,
               start_name = ?,
               end_name = ?,
               start_instructions = ?
         WHERE id = ?
        """,
        (start_lat, start_lng, end_lat, end_lng, start_name, end_name, start_instructions, row["id"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="Only patch these trail names")
    parser.add_argument("--skip-tags", action="store_true", help="Don't fetch OSM tags for unchanged trails (faster)")
    parser.add_argument("--sleep", type=float, default=1.5, help="Sleep between Overpass calls")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row

    print("Ensuring schema columns…")
    ensure_columns(conn)

    rows = list(conn.execute("SELECT * FROM hikes ORDER BY popularity DESC"))
    print(f"Loaded {len(rows)} trails")

    seed_index = load_seed_index()
    only = set(args.only or [])

    refetched = 0
    patched = 0
    skipped = 0

    for r in rows:
        name = r["name"]
        if only and name not in only:
            continue
        key = name.strip().lower()
        seed = seed_index.get(key)

        if seed and int(seed["osm_id"]) != int(r["osm_id"] or 0):
            ok = fully_rebuild_row(conn, seed, r["id"])
            if ok:
                refetched += 1
            else:
                skipped += 1
            conn.commit()
            time.sleep(args.sleep)
        else:
            try:
                patch_existing_row(conn, r, skip_tags=args.skip_tags, sleep=args.sleep)
                patched += 1
            except Exception as e:
                print(f"  patch FAIL {safe(name)}: {e}")
                skipped += 1
            if (patched + refetched) % 10 == 0:
                conn.commit()

    conn.commit()
    conn.close()
    print()
    print(f"Done. re-fetched={refetched}  patched-in-place={patched}  skipped={skipped}")


if __name__ == "__main__":
    main()
