#!/usr/bin/env python3
"""Fast Europe city cards: Wikipedia summary + thumbnail, no Commons crawl.

Used when the full enrichment pipeline is rate-limited. Writes SQLite only;
follow with `sync-city-details.py` to persist into details.json.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog_paths import CITIES_DB  # noqa: E402
from place_activities import city_activities, city_tips  # noqa: E402
from place_categories import CAPITALS_BY_CC, is_capital_name  # noqa: E402
from text_phrase import complete_phrase, sentences, summary_paragraph  # noqa: E402

TIPS_PATH = ROOT / "scripts" / "data" / "country-travel-tips.json"
USER_AGENT = "Trailthread/1.0 (europe lite city cards)"
OCEANIA_CC = {
    "FJ", "PG", "SB", "VU", "NC", "PF", "WS", "AS", "TO", "CK", "NU",
    "PW", "GU", "MP", "FM", "MH", "KI", "NR", "TV", "WF", "NF",
}
TITLE_OVERRIDES = {
    "luxembourg-lu": "Luxembourg City",
    "monaco-mc": "Monaco",
    "san-marino-sm": "City of San Marino",
    "vatican-city-va": "Vatican City",
    "chisinau-md": "Chișinău",
    "kyiv-ua": "Kyiv",
    "pristina-xk": "Pristina",
    "andorra-la-vella-ad": "Andorra la Vella",
    "reykjavik-is": "Reykjavík",
}

HIGHLIGHT_TITLES = (
    "Iconic landmarks",
    "Historic old town",
    "Museums & culture",
    "Architecture",
    "City views",
    "Markets & streets",
)


def http_json(url: str, *, timeout: float = 12.0, retries: int = 5) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            last = err
            if err.code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            if err.code == 404:
                return {}
            time.sleep(1.5)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last = err
            time.sleep(2.0 + attempt)
    raise RuntimeError(f"GET failed {url}: {last}")


def wiki_search(name: str, country: str) -> str | None:
    params = urllib.parse.urlencode({
        "action": "opensearch",
        "search": f"{name}, {country}",
        "limit": 1,
        "namespace": 0,
        "format": "json",
    })
    data = http_json(f"https://en.wikipedia.org/w/api.php?{params}")
    titles = data[1] if isinstance(data, list) and len(data) > 1 else []
    return titles[0] if titles else None


def wiki_summary(title: str) -> dict:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    data = http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}")
    if not isinstance(data, dict):
        return {}
    extract = (data.get("extract") or "").strip()
    thumb = ((data.get("thumbnail") or {}).get("source") or "").strip()
    original = ((data.get("originalimage") or {}).get("source") or "").strip()
    return {
        "extract": extract,
        "description": (data.get("description") or "").strip(),
        "title": data.get("title") or title,
        "thumbnail": original or thumb,
    }


def highlights_from_photos(photos: list[dict]) -> list[dict]:
    out = []
    for i, photo in enumerate(photos[:6]):
        url = photo.get("url") or ""
        if not url:
            continue
        out.append({
            "title": HIGHLIGHT_TITLES[i % len(HIGHLIGHT_TITLES)],
            "url": url,
            "caption": photo.get("caption") or HIGHLIGHT_TITLES[i % len(HIGHLIGHT_TITLES)],
            "source": photo.get("source") or "Wikipedia",
        })
    return out


def europe_capital_ids(conn: sqlite3.Connection) -> list[str]:
    europe_ccs = [cc for cc in CAPITALS_BY_CC if cc not in OCEANIA_CC]
    rows = conn.execute(
        f"SELECT id, name, cc FROM cities WHERE region_id = 'europe' AND cc IN ({','.join('?' * len(europe_ccs))})",
        europe_ccs,
    ).fetchall()
    return [cid for cid, name, cc in rows if is_capital_name(name, cc)]


def pending_ids(conn: sqlite3.Connection, args: argparse.Namespace) -> list[str]:
    if args.ids:
        return [part.strip() for part in args.ids.split(",") if part.strip()]
    if args.capitals:
        ids = europe_capital_ids(conn)
        if args.force:
            return ids
        rows = conn.execute(
            f"SELECT id FROM cities WHERE id IN ({','.join('?' * len(ids))}) "
            "AND (enriched = 0 OR general LIKE '%future deep-dive%' OR photos_json = '[]')",
            ids,
        ).fetchall()
        return [r[0] for r in rows]
    query = "SELECT id FROM cities WHERE region_id = 'europe' AND source != 'trip'"
    params: list = []
    if not args.force:
        query += " AND (enriched = 0 OR general LIKE '%future deep-dive%' OR photos_json = '[]')"
    if args.tier != "all":
        query += " AND tier = ?"
        params.append(args.tier)
    if getattr(args, "min_pop", 0):
        query += " AND pop >= ?"
        params.append(args.min_pop)
    query += " ORDER BY pop DESC"
    if args.limit:
        query += " LIMIT ?"
        params.append(args.limit)
    return [r[0] for r in conn.execute(query, params).fetchall()]


def enrich_one(row: sqlite3.Row, tips_db: dict) -> dict | None:
    name = row["name"]
    country = row["country"]
    title = TITLE_OVERRIDES.get(row["id"]) or name
    summary = wiki_summary(title)
    if len((summary.get("extract") or "")) < 40:
        found = wiki_search(name, country)
        if found and found != title:
            summary = wiki_summary(found)
    extract = summary.get("extract") or ""
    description = summary.get("description") or ""
    if len(extract) < 40:
        return None

    general = summary_paragraph(extract, 420) or f"{name} — {description}"[:420]
    if len(general) < 80:
        fallback = f"{name} is a city in {country}. {extract} {description}".strip()
        general = (extract if len(extract) >= 80 else fallback)[:420]
    tagline = complete_phrase(description or (sentences(extract)[0] if sentences(extract) else name), 88)
    category = row["category"] or "city"
    locale = row["locale"] or "inland"
    activities = city_activities(category, locale, f"city:{row['id']}")
    tips = city_tips(category, locale, country, f"city:{row['id']}", country_tips=tips_db.get(country) or tips_db.get("default"))
    photos = []
    thumb = summary.get("thumbnail")
    if thumb:
        photos.append({"url": thumb, "caption": name, "source": "Wikipedia"})
    if len(photos) < 1 and len(general) < 80:
        return None
    highlights = highlights_from_photos(photos)
    return {
        "general": general,
        "tagline": tagline,
        "activities_json": json.dumps(activities, ensure_ascii=False),
        "tips_json": json.dumps(tips, ensure_ascii=False),
        "photos_json": json.dumps(photos, ensure_ascii=False),
        "highlights_json": json.dumps(highlights, ensure_ascii=False),
        "enriched": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capitals", action="store_true")
    parser.add_argument("--tier", choices=["major", "regional", "town", "all"], default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-pop", type=int, default=0, help="Skip cities below this population")
    parser.add_argument("--ids", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args()

    tips_db = json.loads(TIPS_PATH.read_text(encoding="utf-8")) if TIPS_PATH.is_file() else {}
    conn = sqlite3.connect(CITIES_DB, timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    ids = pending_ids(conn, args)
    print(f"Lite-enriching {len(ids)} Europe cities...", flush=True)

    done = 0
    failed = 0
    for index, cid in enumerate(ids, start=1):
        row = conn.execute("SELECT * FROM cities WHERE id = ?", (cid,)).fetchone()
        if not row:
            failed += 1
            print(f"  {index}/{len(ids)} missing {cid}".encode("ascii", "replace").decode("ascii"), flush=True)
            continue
        if row["source"] == "trip" and not args.force:
            print(f"  {index}/{len(ids)} skip trip {row['name']}".encode("ascii", "replace").decode("ascii"), flush=True)
            continue
        try:
            payload = enrich_one(row, tips_db)
        except Exception as err:
            failed += 1
            print(f"  {index}/{len(ids)} fail {row['name']}: {err}".encode("ascii", "replace").decode("ascii"), flush=True)
            time.sleep(args.sleep)
            continue
        if not payload:
            failed += 1
            print(f"  {index}/{len(ids)} thin {row['name']}".encode("ascii", "replace").decode("ascii"), flush=True)
            time.sleep(args.sleep)
            continue
        conn.execute(
            """
            UPDATE cities SET
                general = ?, tagline = ?, activities_json = ?, tips_json = ?,
                photos_json = ?, highlights_json = ?, enriched = 1,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                payload["general"], payload["tagline"], payload["activities_json"],
                payload["tips_json"], payload["photos_json"], payload["highlights_json"],
                cid,
            ),
        )
        conn.commit()
        done += 1
        print(f"  {index}/{len(ids)} {row['name']}".encode("ascii", "replace").decode("ascii"), flush=True)
        time.sleep(args.sleep)

    conn.close()
    print(f"Done. Enriched {done} ({failed} failed/skipped).", flush=True)
    return 0 if failed == 0 or done > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
