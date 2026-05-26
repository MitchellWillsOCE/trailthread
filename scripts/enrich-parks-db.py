#!/usr/bin/env python3
"""Enrich national park rows: copy, photos, highlights carousel, tips.

Process one country at a time (default order starts with Montenegro).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio, safe_geosearch, safe_wiki_search, title_from_activity  # noqa: E402
import enrichment_sources as src  # noqa: E402
from photo_validation import filter_viewable_photos, photo_url_is_viewable, resolve_direct_image_url  # noqa: E402
from text_phrase import highlight_line, sentences, summary_paragraph  # noqa: E402
from place_activities import park_activities as _pool_park_activities, park_tips as _pool_park_tips  # noqa: E402

# Adriatic-first rollout; extend as more parks are seeded per country.
ENRICH_COUNTRY_ORDER = [
    "Montenegro",
    "Croatia",
    "Slovenia",
    "Albania",
    "Bosnia and Herzegovina",
    "Serbia",
    "North Macedonia",
    "Greece",
    "Italy",
    "France",
    "Spain",
    "Portugal",
    "Germany",
    "Austria",
    "Switzerland",
    "Poland",
    "Romania",
    "Bulgaria",
    "Norway",
    "Sweden",
    "Iceland",
    "Ireland",
    "United Kingdom",
    "Turkey",
]

COUNTRY_ALIASES = {
    "me": "Montenegro",
    "montenegro": "Montenegro",
    "hr": "Croatia",
    "croatia": "Croatia",
    "si": "Slovenia",
    "slovenia": "Slovenia",
}


def load_photos_mod():
    path = ROOT / "scripts" / "fetch-location-photos.py"
    spec = importlib.util.spec_from_file_location("fetch_photos", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


from catalog_paths import PARKS_DB as DB  # noqa: E402
TIPS_PATH = ROOT / "scripts" / "data" / "park-enrich-tips.json"
MIN_SUMMARY = 72
MIN_PHOTOS = 1

UPDATE_SQL = """
    UPDATE parks SET
        summary = ?, tagline = ?, stay = ?, activities_json = ?, tips_json = ?,
        photos_json = ?, highlights_json = ?, enriched = ?, updated_at = datetime('now')
    WHERE id = ?
"""

PARK_THEMES = [
    ("wildlife", "Wildlife watching"),
    ("hiking trail", "Scenic hiking"),
    ("waterfall", "Waterfalls & lakes"),
    ("viewpoint", "Panoramas"),
    ("forest", "Ancient forests"),
    ("canyon", "Gorges & valleys"),
]


def normalize_country(value: str) -> str:
    key = (value or "").strip()
    if not key:
        return ""
    return COUNTRY_ALIASES.get(key.lower(), key)


def pick_tips(country: str, park_id: str, tips_db: dict, *, category: str = "national-park") -> list[str]:
    pool_tips = _pool_park_tips(category or "national-park", f"park:{park_id}")
    country_pool = (tips_db.get(country) or [])
    if country_pool:
        offset = sum(ord(c) for c in park_id) % len(country_pool)
        pool_tips.append(country_pool[offset])
    return pool_tips[:4]


def build_park_activities(extract: str, name: str, *, category: str = "national-park", park_id: str = "") -> list[str]:
    return _pool_park_activities(category or "national-park", f"park:{park_id or name}")


def ensure_summary(name: str, country: str, area: float, bio: int, extract: str, activities: list[str]) -> str:
    summary = summary_paragraph(extract, 420) if extract else ""
    if len(summary) < MIN_SUMMARY:
        summary = (
            f"{name} is a protected national park in {country}, "
            f"covering roughly {int(area):,} km² of landscapes valued for nature and outdoor recreation. "
            f"Biodiversity is rated {bio}/5 in our catalog."
        )
    if len(summary) < MIN_SUMMARY and activities:
        extra = " ".join(activities[:2])
        summary = f"{summary.rstrip('.')}. {extra}"
    return summary[:520].strip()


def gather_park_photos(
    name: str,
    country: str,
    lat: float,
    lng: float,
    bundle: src.PlaceBundle,
    photos_mod,
) -> list[dict]:
    photos = src.dedupe_photos(bundle.photos, cap=8)

    try:
        curated = photos_mod.collect_photos(name, country, lng, lat)
        photos = src.dedupe_photos(photos + curated, cap=8)
    except Exception as err:
        if "429" not in str(err):
            pass

    if len(photos) < MIN_PHOTOS and lat and lng:
        for entry in safe_geosearch(photos_mod, lat, lng, limit=8):
            photos = src.dedupe_photos(photos + [entry], cap=8)
            if len(photos) >= MIN_PHOTOS:
                break
            time.sleep(0.7)

    if len(photos) < MIN_PHOTOS:
        for query in (name, f"{name} national park", f"{name} {country}"[:80]):
            for entry in safe_wiki_search(photos_mod, query, limit=4):
                photos = src.dedupe_photos(photos + [entry], cap=8)
                if len(photos) >= MIN_PHOTOS:
                    break
                time.sleep(0.8)
            if len(photos) >= MIN_PHOTOS:
                break

    return filter_viewable_photos(photos, cap=8, name=name)


def build_park_highlights(name: str, country: str, lat: float, lng: float, photos_mod, photos: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []

    def push(title: str, entry: dict | None) -> None:
        if not entry or len(out) >= 6:
            return
        url = entry.get("url", "")
        if not url or url in seen:
            return
        seen.add(url)
        out.append(
            {
                "title": title_from_activity(title),
                "url": url,
                "caption": entry.get("caption") or title,
                "source": entry.get("source") or "Wikimedia Commons",
            }
        )

    for keyword, label in PARK_THEMES:
        query = f"{name} {keyword}"[:90]
        for entry in safe_wiki_search(photos_mod, query, limit=2):
            push(label, entry)
            if len(out) >= 6:
                break
        time.sleep(1.1)
        if len(out) >= 6:
            break

    if len(out) < 4 and lat and lng:
        for entry in safe_geosearch(photos_mod, lat, lng, limit=6):
            push(name, entry)
            if len(out) >= 6:
                break
            time.sleep(0.6)

    valid: list[dict] = []
    for item in out:
        url = resolve_direct_image_url(item.get("url", ""))
        if url and photo_url_is_viewable(url):
            valid.append({**item, "url": url})
        if len(valid) >= 6:
            break

    if len(valid) < 3:
        for i, p in enumerate(photos[:6]):
            valid.append(
                {
                    "title": PARK_THEMES[i % len(PARK_THEMES)][1],
                    "url": p["url"],
                    "caption": p.get("caption") or name,
                    "source": p.get("source") or "",
                }
            )
    return valid[:6]


def load_text_bundle(name: str, country: str, lat: float, lng: float) -> src.PlaceBundle:
    try:
        return src.merge_city_bundle(name, country, lat, lng, use_commons_geosearch=False)
    except Exception as err:
        print(f"    wikidata/wikipedia skipped ({err}); using fallbacks", flush=True)
        bundle = src.PlaceBundle()
        try:
            wiki_title = src.nominatim_wikipedia_title(lat, lng)
            if wiki_title:
                summary = src.wikipedia_summary(wiki_title)
                if summary.get("extract"):
                    bundle.extract = summary["extract"]
                if summary.get("description"):
                    bundle.description = summary["description"]
                thumb = summary.get("thumbnail")
                if thumb:
                    bundle.photos.append(
                        {
                            "url": src.normalize_photo_url(thumb),
                            "caption": name,
                            "source": "Wikipedia",
                        }
                    )
        except Exception:
            pass
        return bundle


def enrich_row(row: dict, photos_mod, tips_db: dict) -> dict:
    name = row["name"]
    country = row["country"]
    lat, lng = row["lat"], row["lng"]
    area = row["area_km2"] or 50
    bio = row["biodiversity"] or 3

    bundle = load_text_bundle(name, country, lat, lng)
    extract = bundle.extract or bundle.description
    category = (row.get("category") or "national-park") or "national-park"
    activities = build_park_activities(extract, name, category=category, park_id=row["id"])
    summary = ensure_summary(name, country, area, bio, extract, activities)

    tagline = summary_paragraph(bundle.description or sentences(extract)[0] if extract else name, 88)
    if not tagline:
        tagline = f"Wild landscapes · biodiversity {bio}/5"

    stay = (row.get("stay") or "").strip() or "1–2 days"
    tips = pick_tips(country, row["id"], tips_db, category=category)

    photos = gather_park_photos(name, country, lat, lng, bundle, photos_mod)
    highlights = build_park_highlights(name, country, lat, lng, photos_mod, photos)

    qualifies = len(summary) >= MIN_SUMMARY and len(photos) >= MIN_PHOTOS

    return {
        "summary": summary,
        "tagline": tagline,
        "stay": stay,
        "activities_json": json.dumps(activities, ensure_ascii=False),
        "tips_json": json.dumps(tips, ensure_ascii=False),
        "photos_json": json.dumps(photos, ensure_ascii=False),
        "highlights_json": json.dumps(highlights[:6], ensure_ascii=False),
        "enriched": 1 if qualifies else 0,
    }


def countries_in_db(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT country FROM parks ORDER BY country").fetchall()
    return [r[0] for r in rows if r[0]]


def ordered_countries(conn: sqlite3.Connection, start_country: str | None) -> list[str]:
    present = set(countries_in_db(conn))
    order = [c for c in ENRICH_COUNTRY_ORDER if c in present]
    for c in sorted(present):
        if c not in order:
            order.append(c)
    if start_country:
        start = normalize_country(start_country)
        if start in order:
            idx = order.index(start)
            order = order[idx:] + order[:idx]
    return order


def fetch_rows(
    conn: sqlite3.Connection,
    *,
    tier: str,
    limit: int,
    country: str | None,
    cc: str | None,
    force: bool,
) -> list[sqlite3.Row]:
    q = "SELECT * FROM parks WHERE 1=1"
    params: list = []
    if not force:
        q += " AND enriched = 0"
    if tier != "all":
        q += " AND tier = ?"
        params.append(tier)
    if country:
        q += " AND country = ?"
        params.append(normalize_country(country))
    if cc:
        q += " AND cc = ?"
        params.append(cc.lower())
    q += " ORDER BY popularity DESC"
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    return conn.execute(q, params).fetchall()


def enrich_batch(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    photos_mod,
    tips_db: dict,
    *,
    dry_run: bool,
    sleep_min: float,
    sleep_max: float,
) -> int:
    done = 0
    for row in rows:
        row_dict = dict(row)
        try:
            payload = enrich_row(row_dict, photos_mod, tips_db)
        except Exception as err:
            err_s = str(err)
            if "429" in err_s or "Too Many Requests" in err_s:
                print(f"  rate-limited on {row_dict['name']}, retry later", flush=True)
            else:
                print(f"  skip {row_dict['name']}: {err}", flush=True)
            continue
        photo_count = len(json.loads(payload["photos_json"]))
        summary_len = len(payload["summary"])
        if dry_run:
            print(
                f"  would enrich: {row_dict['name']} "
                f"(photos={photo_count}, summary={summary_len} chars)",
                flush=True,
            )
            continue
        conn.execute(
            UPDATE_SQL,
            (
                payload["summary"],
                payload["tagline"],
                payload["stay"],
                payload["activities_json"],
                payload["tips_json"],
                payload["photos_json"],
                payload["highlights_json"],
                payload["enriched"],
                row_dict["id"],
            ),
        )
        conn.commit()
        done += 1
        status = "ok" if payload["enriched"] else "partial"
        print(
            f"  {row_dict['name']} [{status}] "
            f"photos={photo_count} summary={summary_len} chars",
            flush=True,
        )
        time.sleep(random.uniform(sleep_min, sleep_max))
    return done


def main() -> None:
    global args
    parser = argparse.ArgumentParser(description="Enrich parks with descriptions and Wikimedia photos.")
    parser.add_argument("--limit", type=int, default=0, help="Max parks per country/batch")
    parser.add_argument("--tier", choices=["major", "regional", "local", "all"], default="all")
    parser.add_argument("--country", type=str, default="", help="Single country, e.g. Montenegro")
    parser.add_argument("--cc", type=str, default="", help="ISO country code, e.g. me")
    parser.add_argument(
        "--by-country",
        action="store_true",
        help="Process countries in catalog order (Montenegro first)",
    )
    parser.add_argument(
        "--start-country",
        type=str,
        default="Montenegro",
        help="First country when using --by-country",
    )
    parser.add_argument("--force", action="store_true", help="Re-enrich even if already marked enriched")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep-min", type=float, default=1.8)
    parser.add_argument("--sleep-max", type=float, default=3.2)
    args = parser.parse_args()
    configure_stdio()

    if not DB.is_file():
        raise SystemExit(f"Missing {DB}. Run: npm run build:parks")

    photos_mod = load_photos_mod()
    tips_db = json.loads(TIPS_PATH.read_text(encoding="utf-8"))

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    total_done = 0

    country_filter = normalize_country(args.country) if args.country else ""
    cc_filter = args.cc.strip().lower()

    if args.by_country:
        countries = ordered_countries(conn, args.start_country)
        print(f"Country-by-country enrichment ({len(countries)} countries in queue)", flush=True)
        for country_name in countries:
            rows = fetch_rows(
                conn,
                tier=args.tier,
                limit=args.limit,
                country=country_name,
                cc="",
                force=args.force,
            )
            if not rows:
                print(f"=== {country_name} — skip (no pending parks) ===", flush=True)
                continue
            print(f"=== {country_name} ({len(rows)} parks) ===", flush=True)
            total_done += enrich_batch(
                conn,
                rows,
                photos_mod,
                tips_db,
                dry_run=args.dry_run,
                sleep_min=args.sleep_min,
                sleep_max=args.sleep_max,
            )
    else:
        if not country_filter and not cc_filter:
            country_filter = normalize_country(args.start_country) or "Montenegro"
        rows = fetch_rows(
            conn,
            tier=args.tier,
            limit=args.limit,
            country=country_filter,
            cc=cc_filter,
            force=args.force,
        )
        label = country_filter or cc_filter or "all"
        print(f"=== {label} ({len(rows)} parks) ===", flush=True)
        total_done = enrich_batch(
            conn,
            rows,
            photos_mod,
            tips_db,
            dry_run=args.dry_run,
            sleep_min=args.sleep_min,
            sleep_max=args.sleep_max,
        )

    conn.close()
    print(f"Done. Enriched {total_done} parks.", flush=True)


if __name__ == "__main__":
    main()
