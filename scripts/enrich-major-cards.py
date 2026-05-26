#!/usr/bin/env python3
"""Build image highlight carousels for major-tier cities."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import safe_geosearch, safe_wiki_search, title_from_activity  # noqa: E402
from photo_validation import photo_url_is_viewable, resolve_direct_image_url  # noqa: E402
from text_phrase import highlight_line, sentences  # noqa: E402

DB = ROOT / "Trip" / "cities" / "cities.db"

THEME_TITLES = [
    ("landmark", "Iconic landmarks"),
    ("old town", "Historic old town"),
    ("museum", "Museums & culture"),
    ("cathedral", "Architecture"),
    ("skyline", "City views"),
    ("market", "Markets & streets"),
]


def load_photos_mod():
    path = ROOT / "scripts" / "fetch-location-photos.py"
    spec = importlib.util.spec_from_file_location("fetch_photos", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def highlights_from_photos(photos_raw: str, titles: list[str]) -> list[dict]:
    try:
        photos = json.loads(photos_raw or "[]")
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for i, photo in enumerate(photos[:6]):
        if isinstance(photo, str):
            url = photo
            caption = titles[i % len(titles)] if titles else "Highlight"
        else:
            url = photo.get("url", "")
            caption = photo.get("caption") or (titles[i % len(titles)] if titles else "Highlight")
        title = titles[i % len(titles)] if titles else title_from_activity(caption)
        direct = resolve_direct_image_url(url)
        if direct and photo_url_is_viewable(direct):
            out.append({"title": title_from_activity(title), "url": direct, "caption": caption, "source": "City photos"})
    return out


def build_highlights(
    name: str,
    country: str,
    lat: float,
    lng: float,
    extract: str,
    photos_json: str,
    photos_mod,
) -> list[dict]:
    seen_urls: set[str] = set()
    out: list[dict] = []

    def push(title: str, entry: dict | None) -> None:
        if not entry or len(out) >= 6:
            return
        url = entry.get("url", "")
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        out.append(
            {
                "title": title_from_activity(title),
                "url": url,
                "caption": entry.get("caption") or title,
                "source": entry.get("source") or "Wikimedia Commons",
            }
        )

    activity_titles = [
        title_from_activity(highlight_line(s, 120) or "")
        for s in sentences(extract or "")[1:6]
        if highlight_line(s, 120)
    ]

    for keyword, label in THEME_TITLES:
        query = f"{name} {keyword} {country}"[:120]
        for entry in safe_wiki_search(photos_mod, query, limit=2):
            push(label, entry)
            if len(out) >= 6:
                break
        time.sleep(1.2)
        if len(out) >= 6:
            break

    if len(out) < 4 and lat and lng:
        for entry in safe_geosearch(photos_mod, lat, lng, limit=6):
            push(title_from_activity(entry.get("caption") or name), entry)
            if len(out) >= 6:
                break
            time.sleep(0.8)

    if len(out) < 3:
        fallback = highlights_from_photos(photos_json, activity_titles or [t for _, t in THEME_TITLES])
        for item in fallback:
            if item["url"] not in seen_urls:
                out.append(item)
                seen_urls.add(item["url"])
            if len(out) >= 6:
                break

    valid: list[dict] = []
    for item in out:
        url = resolve_direct_image_url(item.get("url", ""))
        if url and photo_url_is_viewable(url):
            valid.append({**item, "url": url})
        if len(valid) >= 6:
            break
    return valid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    photos_mod = load_photos_mod()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    q = """
        SELECT id, name, country, lat, lng, general, photos_json, highlights_json
        FROM cities WHERE tier = 'major' AND source != 'trip'
        ORDER BY pop DESC
    """
    if args.limit:
        q += f" LIMIT {args.limit}"
    rows = conn.execute(q).fetchall()
    done = 0
    for row in rows:
        try:
            existing = json.loads(row["highlights_json"] or "[]")
        except json.JSONDecodeError:
            existing = []
        if len(existing) >= 4:
            continue
        highlights = build_highlights(
            row["name"],
            row["country"],
            row["lat"],
            row["lng"],
            row["general"] or "",
            row["photos_json"] or "[]",
            photos_mod,
        )
        if len(highlights) < 3:
            print(f"  skip {row['name']}: only {len(highlights)} highlights", flush=True)
            continue
        payload = json.dumps(highlights, ensure_ascii=False)
        if args.dry_run:
            print(f"  would set {row['name']}: {len(highlights)} cards", flush=True)
            continue
        conn.execute(
            "UPDATE cities SET highlights_json = ?, updated_at = datetime('now') WHERE id = ?",
            (payload, row["id"]),
        )
        conn.commit()
        done += 1
        print(f"  {row['name']}: {len(highlights)} highlights", flush=True)
        time.sleep(2.0)
    conn.close()
    print(f"Done. Updated {done} major cities.", flush=True)


if __name__ == "__main__":
    main()
