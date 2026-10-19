#!/usr/bin/env python3
"""Enrich city rows in SQLite from Wikipedia, Wikimedia, and country tips."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio, strip_html  # noqa: E402
import enrichment_sources as src  # noqa: E402
from photo_validation import filter_viewable_photos  # noqa: E402
from text_phrase import complete_phrase, highlight_line, sentences, summary_paragraph  # noqa: E402
from place_activities import city_activities as _pool_city_activities, city_tips as _pool_city_tips  # noqa: E402

from catalog_paths import CITIES_DB as DB_PATH  # noqa: E402
TIPS_PATH = ROOT / "scripts" / "data" / "country-travel-tips.json"
USER_AGENT = "Trailthread/1.0 (city catalog enrichment)"
STUB_PHRASE = "future deep-dive"
MIN_PHOTOS_FOR_CARD = 1
MIN_GENERAL_LEN = 72


UPDATE_SQL = """
    UPDATE cities SET
        general = ?, tagline = ?, activities_json = ?, tips_json = ?,
        photos_json = ?, enriched = ?, updated_at = datetime('now')
    WHERE id = ?
"""

# Shared worker globals (thread pool — one throttle for all HTTP)
_worker_photos = None
_worker_tips: dict = {}
_worker_photo_mode = "auto"
_worker_force = False
_db_lock = threading.Lock()


def load_photo_module():
    path = ROOT / "scripts" / "fetch-location-photos.py"
    spec = importlib.util.spec_from_file_location("fetch_photos", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http_json(url: str, params: dict | None = None, *, retries: int = 8) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    result = src.http_get_json(full, retries=retries)
    return result if isinstance(result, dict) else {}


def wiki_article_near(lat: float, lng: float, radius_m: int = 12000) -> str | None:
    data = http_json(
        "https://en.wikipedia.org/w/api.php",
        {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lng}",
            "gsradius": radius_m,
            "gslimit": 1,
            "format": "json",
        },
    )
    items = data.get("query", {}).get("geosearch", [])
    return items[0]["title"] if items else None


def wiki_article_search(name: str, country: str) -> str | None:
    data = http_json(
        "https://en.wikipedia.org/w/api.php",
        {
            "action": "opensearch",
            "search": f"{name}, {country}",
            "limit": 1,
            "namespace": 0,
            "format": "json",
        },
    )
    titles = data[1] if len(data) > 1 else []
    return titles[0] if titles else None


def wiki_summary(title: str) -> dict:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    data = http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}")
    extract = strip_html(data.get("extract_html") or data.get("extract") or "")
    thumb = (data.get("thumbnail") or {}).get("source") or ""
    return {
        "extract": extract,
        "description": (data.get("description") or "").strip(),
        "title": data.get("title") or title,
        "thumbnail": thumb,
    }


def photos_from_summary(summary: dict, name: str) -> list[dict]:
    thumb = summary.get("thumbnail")
    if not thumb:
        return []
    return [{"url": thumb, "caption": name, "source": "Wikipedia"}]


HIGHLIGHT_MAX = 120
TAGLINE_MAX = 88


def build_activities(extract: str, name: str, *, category: str, locale: str, city_id: str) -> list[str]:
    """Category- and locale-aware activities. Falls back to the shared pools."""
    return _pool_city_activities(category or "town", locale or "inland", f"city:{city_id or name}")


def pick_tips(country: str, city_id: str, tips_db: dict, *, category: str = "town", locale: str = "inland") -> list[str]:
    return _pool_city_tips(
        category or "town",
        locale or "inland",
        country or "",
        f"city:{city_id}",
        country_tips=tips_db.get(country) or tips_db.get("default") or None,
    )


def city_qualifies_for_card(general: str, photos: list[dict]) -> bool:
    text = (general or "").strip()
    if STUB_PHRASE in text.lower():
        return False
    if len(text) < MIN_GENERAL_LEN:
        return False
    if len(photos) < MIN_PHOTOS_FOR_CARD:
        return False
    return True


def enrich_row_dict(row: dict, photos_mod, tips_db: dict, *, photo_mode: str = "fast") -> dict:
    name = row["name"]
    country = row["country"]
    lat, lng = row["lat"], row["lng"]
    tier = row["tier"] or "town"

    use_commons = photo_mode == "full" or (photo_mode == "auto" and tier in ("major", "regional"))
    commons_fn = photos_mod.collect_photos if use_commons else None

    bundle = src.merge_city_bundle(
        name,
        country,
        lat,
        lng,
        use_commons_geosearch=use_commons,
        commons_collector=commons_fn,
    )

    extract = bundle.extract or bundle.description
    tagline = row.get("tagline") or f"Discover {name}"
    if bundle.description:
        tagline = complete_phrase(bundle.description, TAGLINE_MAX)
    elif extract:
        tagline = complete_phrase(sentences(extract)[0] if sentences(extract) else name, TAGLINE_MAX)

    general = summary_paragraph(extract, 420) if extract else ""
    if not general and bundle.description:
        general = f"{name} — {bundle.description[:360]}".strip()
    if not general:
        general = f"{name} is a city in {country} worth exploring on foot."

    def _row_get(key: str, fallback: str) -> str:
        try:
            val = row[key]
        except (IndexError, KeyError):
            return fallback
        return (val or fallback) or fallback
    category = _row_get("category", "town")
    locale = _row_get("locale", "inland")
    activities = build_activities(extract, name, category=category, locale=locale, city_id=row["id"])
    tips = pick_tips(country, row["id"], tips_db, category=category, locale=locale)

    photos = filter_viewable_photos(bundle.photos, cap=8, name=name)
    qualifies = city_qualifies_for_card(general, photos)

    return {
        "general": general,
        "tagline": tagline,
        "activities_json": json.dumps(activities, ensure_ascii=False),
        "tips_json": json.dumps(tips, ensure_ascii=False),
        "photos_json": json.dumps(photos, ensure_ascii=False),
        "enriched": 1 if qualifies else 0,
    }


def _init_worker(photo_mode: str, tips_path: str, force: bool = False) -> None:
    global _worker_photos, _worker_tips, _worker_photo_mode, _worker_force
    _worker_photos = load_photo_module()
    _worker_tips = json.loads(Path(tips_path).read_text(encoding="utf-8"))
    _worker_photo_mode = photo_mode
    _worker_force = force
    time.sleep(random.uniform(0, 1.5))


def _enrich_city_task(city_id: str) -> tuple[str, bool, str]:
    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM cities WHERE id = ?", (city_id,)).fetchone()
        if not row:
            return city_id, False, "not found"
        if row["source"] == "trip":
            return city_id, True, "skipped"
        if row["enriched"] and not _worker_force:
            return city_id, True, "skipped"

        row_dict = dict(row)
        payload = enrich_row_dict(row_dict, _worker_photos, _worker_tips, photo_mode=_worker_photo_mode)
        with _db_lock:
            conn.execute(
                UPDATE_SQL,
                (
                    payload["general"],
                    payload["tagline"],
                    payload["activities_json"],
                    payload["tips_json"],
                    payload["photos_json"],
                    payload["enriched"],
                    city_id,
                ),
            )
            conn.commit()
        return city_id, True, row_dict["name"]
    except Exception as err:
        return city_id, False, str(err)
    finally:
        conn.close()


def default_workers(requested: int) -> int:
    cpus = os.cpu_count() or 4
    if requested > 0:
        return max(1, requested)
    # Multi-source pipeline (Wikidata/DBpedia) tolerates more workers than Wikipedia-only.
    return max(1, min(cpus - 2, 12))


def europe_capital_ids(conn: sqlite3.Connection) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from place_categories import CAPITALS_BY_CC, is_capital_name

    oceania = {
        "FJ", "PG", "SB", "VU", "NC", "PF", "WS", "AS", "TO", "CK", "NU",
        "PW", "GU", "MP", "FM", "MH", "KI", "NR", "TV", "WF", "NF",
    }
    ids: list[str] = []
    rows = conn.execute(
        "SELECT id, name, cc FROM cities WHERE region_id = 'europe' AND cc IN ({})".format(
            ",".join("?" * (len(CAPITALS_BY_CC) - len(oceania)))
        ),
        [cc for cc in CAPITALS_BY_CC if cc not in oceania],
    ).fetchall()
    for cid, name, cc in rows:
        if is_capital_name(name, cc):
            ids.append(cid)
    return ids


def fetch_pending_ids(
    tier: str,
    limit: int,
    *,
    ids: list[str] | None = None,
    capitals: bool = False,
    force: bool = False,
) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    if ids:
        wanted = [cid.strip() for cid in ids if cid.strip()]
        if wanted and not force:
            rows = conn.execute(
                f"SELECT id FROM cities WHERE id IN ({','.join('?' * len(wanted))}) "
                "AND enriched = 0 AND source != 'trip'",
                wanted,
            ).fetchall()
            wanted = [r[0] for r in rows]
        conn.close()
        return wanted
    if capitals:
        wanted = europe_capital_ids(conn)
        if wanted and not force:
            rows = conn.execute(
                f"SELECT id FROM cities WHERE id IN ({','.join('?' * len(wanted))}) "
                "AND enriched = 0 AND source != 'trip'",
                wanted,
            ).fetchall()
            wanted = [r[0] for r in rows]
        conn.close()
        return wanted
    query = "SELECT id FROM cities WHERE region_id = 'europe'"
    params: list = []
    if not force:
        query += " AND enriched = 0 AND source != 'trip'"
    else:
        query += " AND source != 'trip'"
    if tier != "all":
        query += " AND tier = ?"
        params.append(tier)
    query += " ORDER BY pop DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    result = [r[0] for r in conn.execute(query, params).fetchall()]
    conn.close()
    return result


def print_stats() -> None:
    conn = sqlite3.connect(DB_PATH)
    enriched = conn.execute("SELECT COUNT(*) FROM cities WHERE enriched = 1").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    conn.close()
    print(f"Database: {enriched}/{total} cities enriched.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max cities to enrich (0 = all pending)")
    parser.add_argument("--tier", choices=["major", "regional", "town", "all"], default="all")
    parser.add_argument("--ids", default="", help="Comma-separated city ids to enrich")
    parser.add_argument("--capitals", action="store_true", help="Enrich European capital cities only")
    parser.add_argument("--force", action="store_true", help="Re-enrich even if already flagged enriched")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--photos",
        choices=["fast", "auto", "full"],
        default="auto",
        help="fast=Wikipedia thumb only; auto=Commons for major; full=Commons for all tiers",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel threads (0 = auto: min(CPU-2, 12); shared API throttle)",
    )
    parser.add_argument("--progress", action="store_true", help="Print each city as it completes")
    args = parser.parse_args()
    configure_stdio()

    if not DB_PATH.is_file():
        raise SystemExit(f"Missing {DB_PATH}. Run: npm run build:db")

    worker_count = default_workers(args.workers)
    explicit_ids = [part.strip() for part in args.ids.split(",") if part.strip()]
    city_ids = fetch_pending_ids(
        args.tier,
        args.limit,
        ids=explicit_ids or None,
        capitals=args.capitals,
        force=args.force,
    )

    if not city_ids:
        print("No pending cities to enrich.", flush=True)
        print_stats()
        return

    print(
        f"Enriching {len(city_ids)} cities (photos={args.photos}, workers={worker_count})…",
        flush=True,
    )

    if args.dry_run:
        for cid in city_ids[:20]:
            print(f"  would enrich: {cid}")
        if len(city_ids) > 20:
            print(f"  … and {len(city_ids) - 20} more")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()

    done = 0
    failed = 0

    if worker_count == 1:
        _init_worker(args.photos, str(TIPS_PATH), force=args.force)
        for index, city_id in enumerate(city_ids, start=1):
            cid, ok, msg = _enrich_city_task(city_id)
            if ok and msg != "skipped":
                done += 1
            elif not ok:
                failed += 1
                print(f"  skip {cid}: {msg}", flush=True)
            if args.progress or index % 10 == 0 or index == len(city_ids):
                print(f"  {index}/{len(city_ids)} — {msg}", flush=True)
    else:
        _init_worker(args.photos, str(TIPS_PATH), force=args.force)
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(_enrich_city_task, cid): cid for cid in city_ids}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                cid, ok, msg = future.result()
                if ok and msg not in ("skipped",):
                    done += 1
                elif not ok:
                    failed += 1
                    if failed <= 30 or failed % 50 == 0:
                        print(f"  skip {cid}: {msg}", flush=True)
                if args.progress or completed % 25 == 0 or completed == len(city_ids):
                    print(f"  {completed}/{len(city_ids)} — last: {msg}", flush=True)

    print(f"Done. Enriched {done} this run ({failed} failed/skipped).", flush=True)
    print_stats()


if __name__ == "__main__":
    main()
