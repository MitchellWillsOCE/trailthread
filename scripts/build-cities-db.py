#!/usr/bin/env python3
"""Import city catalog into SQLite from GeoJSON + details JSON."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from place_kinds import is_park_place_name, load_park_names  # noqa: E402

SCHEMA_PATH = ROOT / "scripts" / "schema" / "cities.sql"
CITIES_ROOT = ROOT / "Trip" / "cities"
DB_PATH = ROOT / "Trip" / "cities" / "cities.db"
MANIFEST_PATH = ROOT / "Trip" / "cities" / "manifest.json"

REGION_LABELS = {
    "europe": "Europe",
    "oceania": "Oceania",
}


def load_json_list(value, default=None):
    if default is None:
        default = []
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def is_enriched(detail: dict) -> int:
    general = detail.get("general") or ""
    if "future deep-dive" in general:
        return 0
    if detail.get("source") == "trip":
        return 1
    if len(load_json_list(detail.get("photos"))) >= 1 and len(general) > 60:
        return 1
    return 1 if len(general) > 80 else 0


def discover_regions() -> list[dict]:
    regions = []
    for geojson_path in sorted(CITIES_ROOT.glob("*/cities.geojson")):
        region_id = geojson_path.parent.name
        details_path = geojson_path.with_name("details.json")
        regions.append(
            {
                "id": region_id,
                "label": REGION_LABELS.get(region_id, region_id.replace("-", " ").title()),
                "geojson": geojson_path,
                "details": details_path,
                "legacyGeojson": f"./Trip/cities/{region_id}/cities.geojson",
            }
        )
    return regions


def main() -> None:
    regions = discover_regions()
    if not regions:
        raise SystemExit(f"Missing city GeoJSON files under {CITIES_ROOT}. Run: npm run build:cities")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DB_PATH.with_suffix(".db.build.tmp")
    if tmp_path.exists():
        tmp_path.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    now = datetime.now(timezone.utc).isoformat()

    insert = """
        INSERT INTO cities (
            id, region_id, name, country, cc, lat, lng, pop, tier, source,
            general, tagline, stay, itinerary,
            activities_json, tips_json, photos_json, highlights_json, enriched, updated_at,
            category, locale
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    park_names = load_park_names()
    rows = []
    manifest_regions = []
    for region in regions:
        geojson = json.loads(region["geojson"].read_text(encoding="utf-8"))
        details = {}
        if region["details"].is_file():
            details = json.loads(region["details"].read_text(encoding="utf-8"))

        region_rows = []
        for feature in geojson.get("features", []):
            props = feature.get("properties") or {}
            name = props.get("name") or ""
            if is_park_place_name(name, park_names):
                continue
            coords = feature.get("geometry", {}).get("coordinates") or [0, 0]
            lng, lat = coords[0], coords[1]
            cid = props.get("id") or ""
            if not cid:
                continue

            detail = details.get(cid, {})
            if is_park_place_name(detail.get("name") or name, park_names):
                continue
            activities = detail.get("activities") or []
            tips = detail.get("tips") or []
            photos = detail.get("photos") or []
            highlights = detail.get("highlights") or []

            region_rows.append(
                (
                    cid,
                    region["id"],
                    detail.get("name") or props.get("name", ""),
                    detail.get("country") or props.get("country", ""),
                    detail.get("cc") or props.get("cc", ""),
                    detail.get("lat", lat),
                    detail.get("lng", lng),
                    int(detail.get("pop") or props.get("pop") or 0),
                    detail.get("tier") or props.get("tier", "town"),
                    detail.get("source") or props.get("source", "catalog"),
                    detail.get("general"),
                    detail.get("tagline"),
                    detail.get("stay"),
                    detail.get("itinerary"),
                    json.dumps(activities, ensure_ascii=False),
                    json.dumps(tips, ensure_ascii=False),
                    json.dumps(photos, ensure_ascii=False),
                    json.dumps(highlights, ensure_ascii=False),
                    is_enriched({**detail, "general": detail.get("general", "")}),
                    now,
                    detail.get("category") or props.get("category", ""),
                    detail.get("locale") or props.get("locale", ""),
                )
            )
        rows.extend(region_rows)
        conn.execute(
            "INSERT INTO regions (id, label, city_count) VALUES (?, ?, ?)",
            (region["id"], region["label"], len(region_rows)),
        )
        manifest_regions.append(
            {
                "id": region["id"],
                "label": region["label"],
                "count": len(region_rows),
                "legacyGeojson": region["legacyGeojson"],
            }
        )

    conn.executemany(insert, rows)
    conn.commit()
    conn.close()

    alt_path = DB_PATH.with_name("cities.db.new")
    try:
        os.replace(tmp_path, DB_PATH)
        if alt_path.exists():
            alt_path.unlink(missing_ok=True)
    except OSError as err:
        try:
            if alt_path.exists():
                alt_path.unlink(missing_ok=True)
            os.replace(tmp_path, alt_path)
            print(
                f"Warning: could not replace locked {DB_PATH} ({err}). "
                f"Wrote {alt_path} — API loads .new until dev server restarts."
            )
        except OSError as alt_err:
            tmp_path.unlink(missing_ok=True)
            raise SystemExit(
                f"Could not replace {DB_PATH} (file may be locked). "
                f"Stop npm run dev, then run: npm run build:db\n{alt_err}"
            ) from alt_err

    manifest = {
        "schemaVersion": 2,
        "storage": "sqlite",
        "database": "./Trip/cities/cities.db",
        "apiBase": "/api/cities",
        "regions": manifest_regions,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"SQLite database: {DB_PATH} ({len(rows)} cities across {len(manifest_regions)} regions)")


if __name__ == "__main__":
    main()
