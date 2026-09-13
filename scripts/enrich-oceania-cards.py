#!/usr/bin/env python3
"""Fill Oceania card fields from photos and activity pools, then reseed."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from place_activities import park_activities, park_tips, poi_activities, poi_tips  # noqa: E402

SEED = ROOT / "scripts" / "data" / "oceania-seed.json"
TIPS = ROOT / "scripts" / "data" / "country-travel-tips.json"
SEED_OCEANIA = ROOT / "scripts" / "seed-oceania.py"
CITIES_DB = ROOT / "Trip" / "cities" / "cities.db"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def highlights_from_photos(row: dict) -> list[dict]:
    existing = row.get("highlights") or []
    if existing:
        return existing
    out = []
    for photo in row.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        url = (photo.get("url") or "").strip()
        if not url:
            continue
        caption = photo.get("caption") or row.get("name") or "Highlight"
        out.append(
            {
                "title": caption.split(",")[0][:48],
                "url": url,
                "caption": caption,
                "source": photo.get("source") or "Wikimedia Commons",
            }
        )
        if len(out) >= 4:
            break
    return out


def main() -> None:
    seed = read_json(SEED)
    country_tips = read_json(TIPS) if TIPS.is_file() else {}
    cities_upgraded = 0
    parks_filled = 0
    pois_filled = 0
    highlight_rows = 0

    for row in seed.get("cities", []):
        if (row.get("category") or "").lower() == "capital" and row.get("tier") != "major":
            row["tier"] = "major"
            cities_upgraded += 1
        before = len(row.get("highlights") or [])
        row["highlights"] = highlights_from_photos(row)
        if len(row.get("highlights") or []) > before:
            highlight_rows += 1

    for row in seed.get("parks", []):
        name = row.get("name") or "park"
        if not row.get("activities"):
            row["activities"] = park_activities(row.get("category") or "national-park", name)
            parks_filled += 1
        if not row.get("tips"):
            row["tips"] = park_tips(row.get("category") or "national-park", name)
        before = len(row.get("highlights") or [])
        row["highlights"] = highlights_from_photos(row)
        if len(row.get("highlights") or []) > before:
            highlight_rows += 1

    for row in seed.get("pois", []):
        name = row.get("name") or "poi"
        category = row.get("category") or "landmark"
        if not row.get("activities"):
            row["activities"] = poi_activities(category, name)
            pois_filled += 1
        if not row.get("tips"):
            tips = poi_tips(category, name)
            extra = country_tips.get(row.get("country") or "", [])
            if extra:
                tips = [*tips[:2], extra[0]]
            row["tips"] = tips
        before = len(row.get("highlights") or [])
        row["highlights"] = highlights_from_photos(row)
        if len(row.get("highlights") or []) > before:
            highlight_rows += 1

    for row in seed.get("hikes", []):
        before = len(row.get("highlights") or [])
        row["highlights"] = highlights_from_photos(row)
        if len(row.get("highlights") or []) > before:
            highlight_rows += 1

    write_json(SEED, seed)
    print(
        f"Updated seed: {cities_upgraded} capitals -> major, "
        f"{parks_filled} parks + {pois_filled} POIs got activities, "
        f"{highlight_rows} rows gained highlights",
        flush=True,
    )

    subprocess.run([sys.executable, str(SEED_OCEANIA)], cwd=ROOT, check=True)
    fill_sqlite_leftovers()


def parse_json_list(blob):
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def fill_sqlite_leftovers() -> None:
    """Fill expansion-only SQLite rows that are not in the seed file."""
    country_tips = read_json(TIPS) if TIPS.is_file() else {}
    highlights = 0
    activities = 0
    capitals = 0

    cities_db = ROOT / "Trip" / "cities" / "cities.db"
    if cities_db.is_file():
        conn = sqlite3.connect(cities_db)
        conn.row_factory = sqlite3.Row
        capitals = conn.execute(
            "UPDATE cities SET tier = 'major' WHERE region_id = 'oceania' AND lower(category) = 'capital' AND tier != 'major'"
        ).rowcount
        for row in conn.execute(
            "SELECT id, name, photos_json, highlights_json FROM cities WHERE region_id = 'oceania'"
        ):
            photos = parse_json_list(row["photos_json"])
            existing = parse_json_list(row["highlights_json"])
            if existing or not photos:
                continue
            built = highlights_from_photos({"name": row["name"], "photos": photos, "highlights": []})
            if built:
                conn.execute(
                    "UPDATE cities SET highlights_json = ? WHERE id = ?",
                    (json.dumps(built, ensure_ascii=False), row["id"]),
                )
                highlights += 1
        conn.commit()
        conn.close()

    for db_name, table, default_cat, activity_fn, tip_fn in (
        ("parks", "parks", "national-park", park_activities, park_tips),
        ("poi", "pois", "landmark", poi_activities, poi_tips),
    ):
        path = ROOT / "Trip" / db_name / f"{db_name}.db"
        if not path.is_file():
            continue
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            f"SELECT id, name, country, category, activities_json, tips_json, photos_json, highlights_json FROM {table} WHERE region_id = 'oceania'"
        ):
            photos = parse_json_list(row["photos_json"])
            existing_hi = parse_json_list(row["highlights_json"])
            if not existing_hi and photos:
                built = highlights_from_photos({"name": row["name"], "photos": photos, "highlights": []})
                if built:
                    conn.execute(
                        f"UPDATE {table} SET highlights_json = ? WHERE id = ?",
                        (json.dumps(built, ensure_ascii=False), row["id"]),
                    )
                    highlights += 1
            acts = [x for x in parse_json_list(row["activities_json"]) if isinstance(x, str)]
            tips = [x for x in parse_json_list(row["tips_json"]) if isinstance(x, str)]
            category = (row["category"] or default_cat).strip() or default_cat
            if not acts:
                acts = activity_fn(category, row["name"] or table)
                activities += 1
            if not tips:
                tips = tip_fn(category, row["name"] or table)
                extra = country_tips.get(row["country"] or "", [])
                if extra:
                    tips = [*tips[:2], extra[0]]
            if not acts or not tips:
                continue
            conn.execute(
                f"UPDATE {table} SET activities_json = ?, tips_json = ? WHERE id = ?",
                (json.dumps(acts, ensure_ascii=False), json.dumps(tips, ensure_ascii=False), row["id"]),
            )
        conn.commit()
        conn.close()

    hikes_db = ROOT / "Trip" / "hikes" / "hikes.db"
    if hikes_db.is_file():
        conn = sqlite3.connect(hikes_db)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(hikes)")}
        if "highlights_json" in columns:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "SELECT id, name, photos_json, highlights_json FROM hikes WHERE region_id = 'oceania'"
            ):
                photos = parse_json_list(row["photos_json"])
                existing = parse_json_list(row["highlights_json"])
                if existing or not photos:
                    continue
                built = highlights_from_photos({"name": row["name"], "photos": photos, "highlights": []})
                if built:
                    conn.execute(
                        "UPDATE hikes SET highlights_json = ? WHERE id = ?",
                        (json.dumps(built, ensure_ascii=False), row["id"]),
                    )
                    highlights += 1
            conn.commit()
        conn.close()

    print(
        f"SQLite leftovers: {capitals} capitals -> major, "
        f"{activities} activity fills, {highlights} highlight fills",
        flush=True,
    )


if __name__ == "__main__":
    main()
