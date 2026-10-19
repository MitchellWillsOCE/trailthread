#!/usr/bin/env python3
"""Write enriched SQLite city cards back to Trip/cities/<region>/details.json.

Keeps later `npm run build:db` from wiping Wikipedia copy that only lives
in SQLite. Also fills empty `highlights_json` from photos so major cards
have a carousel without a second network pass.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog_paths import CITIES_DB  # noqa: E402

DETAILS_PATHS = {
    "europe": ROOT / "Trip" / "cities" / "europe" / "details.json",
    "oceania": ROOT / "Trip" / "cities" / "oceania" / "details.json",
}

HIGHLIGHT_TITLES = (
    "Iconic landmarks",
    "Historic old town",
    "Museums & culture",
    "Architecture",
    "City views",
    "Markets & streets",
)


def load_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def highlights_from_photos(photos: list) -> list[dict]:
    out: list[dict] = []
    for i, photo in enumerate(photos[:6]):
        if isinstance(photo, str):
            url, caption, source = photo, HIGHLIGHT_TITLES[i % len(HIGHLIGHT_TITLES)], "Wikimedia Commons"
        else:
            url = photo.get("url") or ""
            caption = photo.get("caption") or HIGHLIGHT_TITLES[i % len(HIGHLIGHT_TITLES)]
            source = photo.get("source") or "Wikimedia Commons"
        if not url:
            continue
        out.append({
            "title": HIGHLIGHT_TITLES[i % len(HIGHLIGHT_TITLES)],
            "url": url,
            "caption": caption,
            "source": source,
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", choices=["europe", "oceania", "all"], default="europe")
    parser.add_argument("--enriched-only", action="store_true")
    args = parser.parse_args()

    regions = ["europe", "oceania"] if args.region == "all" else [args.region]
    conn = sqlite3.connect(CITIES_DB)
    conn.row_factory = sqlite3.Row

    for region in regions:
        path = DETAILS_PATHS[region]
        if not path.is_file():
            print(f"skip {region}: missing {path}")
            continue
        details = json.loads(path.read_text(encoding="utf-8"))
        query = "SELECT * FROM cities WHERE region_id = ?"
        if args.enriched_only:
            query += " AND enriched = 1"
        rows = conn.execute(query, (region,)).fetchall()
        written = 0
        highlights_filled = 0
        for row in rows:
            photos = load_json_list(row["photos_json"])
            highlights = load_json_list(row["highlights_json"])
            if len(highlights) < 3 and photos:
                highlights = highlights_from_photos(photos)
                conn.execute(
                    "UPDATE cities SET highlights_json = ?, updated_at = datetime('now') WHERE id = ?",
                    (json.dumps(highlights, ensure_ascii=False), row["id"]),
                )
                highlights_filled += 1
            details[row["id"]] = {
                "id": row["id"],
                "name": row["name"],
                "country": row["country"],
                "cc": row["cc"],
                "lat": row["lat"],
                "lng": row["lng"],
                "pop": row["pop"],
                "tier": row["tier"],
                "category": row["category"] or "",
                "locale": row["locale"] or "",
                "general": row["general"] or "",
                "tagline": row["tagline"] or "",
                "stay": row["stay"] or "",
                "itinerary": row["itinerary"] or "",
                "activities": load_json_list(row["activities_json"]),
                "tips": load_json_list(row["tips_json"]),
                "photos": photos,
                "highlights": highlights,
                "source": row["source"] or "catalog",
                "enriched": int(row["enriched"] or 0),
            }
            written += 1
        conn.commit()
        path.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{region}: wrote {written} cards to {path.name} ({highlights_filled} highlights filled)")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
