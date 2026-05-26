#!/usr/bin/env python3
"""Enrich hiking trails in SQLite: Wikipedia summary, trail tips, Commons photos (HTTP-checked)."""

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

from catalog_paths import HIKES_DB as DB_PATH  # noqa: E402
MIN_PHOTOS_FOR_CARD = 1
MIN_SUMMARY_LEN = 80
TIPS_POOL_PATH = ROOT / "scripts" / "data" / "trail-enrich-tips.json"
USER_AGENT = "Trailthread/1.0 (hiking catalog enrichment)"

UPDATE_SQL = """
    UPDATE hikes SET
        summary = ?, tagline = ?, tips_json = ?, photos_json = ?, enriched = ?, updated_at = datetime('now')
    WHERE id = ?
"""

_worker_photos = None
_worker_tip_pool: list[str] = []
_db_lock = threading.Lock()


def load_photo_module():
    path = ROOT / "scripts" / "fetch-location-photos.py"
    spec = importlib.util.spec_from_file_location("fetch_photos", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http_json(url: str, params: dict | None = None, *, retries: int = 8) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            # Gentle pacing reduces 429s and makes progress predictable.
            time.sleep(0.6)
            req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            last_err = err
            if err.code in (429, 503):
                # Commons/Wikipedia can throttle aggressively; be gentle and back off longer.
                time.sleep(min(240, 12 * (2**attempt)))
                continue
            raise
        except OSError as err:
            last_err = err
            time.sleep(min(30, 2 * (attempt + 1)))
    raise RuntimeError(f"HTTP failed after {retries} tries: {last_err}")


def normalize_photo_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http://upload.wikimedia.org/") or u.startswith("http://commons.wikimedia.org/"):
        u = "https://" + u[7:]
    return u


def photo_url_is_reachable(url: str, *, timeout: float = 12.0) -> bool:
    if not url or not url.startswith("http"):
        return False
    headers = {"User-Agent": USER_AGENT}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            ct = (resp.headers.get("Content-Type") or "").lower()
            return ct.startswith("image/") or "webp" in ct or ct in ("application/octet-stream", "")
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers={**headers, "Range": "bytes=0-8191"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200, 206):
                return False
            ct = (resp.headers.get("Content-Type") or "").lower()
            return ct.startswith("image/") or "webp" in ct or "octet-stream" in ct
    except Exception:
        return False


def filter_reachable_photos(photos: list[dict], *, cap: int = 8) -> list[dict]:
    out: list[dict] = []
    for p in photos:
        url = normalize_photo_url(p.get("url", ""))
        if not url:
            continue
        if not photo_url_is_reachable(url):
            continue
        out.append({**p, "url": url})
        if len(out) >= cap:
            break
    return out


def wiki_article_near(lat: float, lng: float, radius_m: int = 12000) -> str | None:
    data = http_json(
        "https://en.wikipedia.org/w/api.php",
        {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lng}",
            "gsradius": radius_m,
            "gslimit": 3,
            "format": "json",
        },
    )
    for item in data.get("query", {}).get("geosearch", []):
        title = item.get("title")
        if title:
            return title
    return None


def wiki_article_search(name: str, country: str) -> str | None:
    data = http_json(
        "https://en.wikipedia.org/w/api.php",
        {
            "action": "opensearch",
            "search": f"{name}, {country}",
            "limit": 2,
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
    return [{"url": normalize_photo_url(thumb), "caption": name, "source": "Wikipedia"}]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) > 28]


def trim(text: str, max_len: int = 72) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1]
    last = cut.rsplit(" ", 1)[0]
    return f"{(last if len(last) > 40 else cut).strip()}…"


def supplement_tips(existing: list[str], extract: str, pool: list[str], hike_id: str) -> list[str]:
    tips: list[str] = []
    for t in existing:
        s = (t or "").strip()
        if len(s) > 8 and s not in tips:
            tips.append(s)
    for s in sentences(extract):
        line = s if len(s) <= 220 else trim(s, 210)
        if len(line) > 35 and line not in tips:
            tips.append(line)
        if len(tips) >= 5:
            break
    rng = random.Random(sum(ord(c) for c in hike_id) % (2**31))
    pool_copy = [p for p in pool if p and p not in tips]
    rng.shuffle(pool_copy)
    for p in pool_copy:
        tips.append(p)
        if len(tips) >= 8:
            break
    return tips[:8]


def hike_qualifies_for_card(summary_text: str, photos: list[dict]) -> bool:
    if len((summary_text or "").strip()) < MIN_SUMMARY_LEN:
        return False
    return len(photos) >= MIN_PHOTOS_FOR_CARD


def enrich_hike_dict(row: dict, photos_mod, tip_pool: list[str]) -> dict:
    name = row["name"]
    country = row["country"]
    lat, lng = row["lat"], row["lng"]
    prev_summary = (row.get("summary") or "").strip()
    prev_tag = (row.get("tagline") or "").strip()

    trail_fn = lambda n, c, lng_, lat_, limit=5: photos_mod.collect_trail_photos(n, c, lng_, lat_, limit=limit)
    bundle = src.merge_trail_bundle(name, country, lat, lng, trail_collector=trail_fn)

    extract = bundle.extract or bundle.description
    if extract and len(extract) > 60:
        summary_text = extract[:2400].strip()
    elif prev_summary:
        summary_text = prev_summary
    else:
        summary_text = (
            f"{name} is a {row.get('length_km') or ''} km hiking route in {country or 'Europe'}, "
            "mapped from OpenStreetMap."
        ).replace("  ", " ").strip()

    if bundle.description:
        tagline = trim(bundle.description, 88)
    elif extract:
        sent = sentences(extract)
        tagline = trim(sent[0], 88) if sent else prev_tag or trim(name, 88)
    else:
        tagline = prev_tag or (f"{row.get('length_km') or ''} km trail".strip() or name)[:88]

    try:
        raw_tips = json.loads(row.get("tips_json") or "[]")
    except json.JSONDecodeError:
        raw_tips = []
    if not isinstance(raw_tips, list):
        raw_tips = []
    tips = supplement_tips(raw_tips, extract, tip_pool, row["id"])

    photos = filter_reachable_photos(bundle.photos, cap=8)
    qualifies = hike_qualifies_for_card(summary_text, photos)

    return {
        "summary": summary_text,
        "tagline": tagline,
        "tips_json": json.dumps(tips, ensure_ascii=False),
        "photos_json": json.dumps(photos, ensure_ascii=False),
        "enriched": 1 if qualifies else 0,
    }


def ensure_hikes_schema(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hikes)").fetchall()}
    if "photos_json" not in cols:
        conn.execute("ALTER TABLE hikes ADD COLUMN photos_json TEXT NOT NULL DEFAULT '[]'")
    if "enriched" not in cols:
        conn.execute("ALTER TABLE hikes ADD COLUMN enriched INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _init_worker(tips_path: str) -> None:
    global _worker_photos, _worker_tip_pool
    _worker_photos = load_photo_module()
    raw = json.loads(Path(tips_path).read_text(encoding="utf-8"))
    _worker_tip_pool = raw if isinstance(raw, list) else raw.get("tips", [])
    time.sleep(random.uniform(0, 1.0))


def _enrich_hike_task(hike_id: str) -> tuple[str, bool, str]:
    conn = sqlite3.connect(DB_PATH, timeout=180)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    try:
        ensure_hikes_schema(conn)
        row = conn.execute("SELECT * FROM hikes WHERE id = ?", (hike_id,)).fetchone()
        if not row:
            return hike_id, False, "not found"
        if row["enriched"]:
            return hike_id, True, "skipped"
        row_dict = dict(row)
        payload = enrich_hike_dict(row_dict, _worker_photos, _worker_tip_pool)
        with _db_lock:
            conn.execute(
                UPDATE_SQL,
                (
                    payload["summary"],
                    payload["tagline"],
                    payload["tips_json"],
                    payload["photos_json"],
                    payload["enriched"],
                    hike_id,
                ),
            )
            conn.commit()
        return hike_id, True, row_dict["name"]
    except Exception as err:
        return hike_id, False, str(err)
    finally:
        conn.close()


def default_workers(requested: int) -> int:
    cpus = os.cpu_count() or 4
    if requested > 0:
        return max(1, requested)
    return max(1, min(cpus - 2, 6))


def fetch_pending_ids(limit: int) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    ensure_hikes_schema(conn)
    q = "SELECT id FROM hikes WHERE region_id = 'europe' AND COALESCE(enriched, 0) = 0 ORDER BY popularity DESC"
    params: list = []
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    ids = [r[0] for r in conn.execute(q, params).fetchall()]
    conn.close()
    return ids


def print_stats() -> None:
    conn = sqlite3.connect(DB_PATH)
    ensure_hikes_schema(conn)
    enriched = conn.execute("SELECT COUNT(*) FROM hikes WHERE COALESCE(enriched,0) = 1").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM hikes").fetchone()[0]
    conn.close()
    print(f"Hikes database: {enriched}/{total} enriched.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max trails to enrich (0 = all pending)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=0, help="Parallel threads (0 = auto, max 6)")
    parser.add_argument("--progress", action="store_true", help="Print each trail as it completes")
    args = parser.parse_args()
    configure_stdio()

    if not DB_PATH.is_file():
        raise SystemExit(f"Missing {DB_PATH}. Run: npm run build:hikes")

    tips_path = str(TIPS_POOL_PATH)
    if not Path(tips_path).is_file():
        raise SystemExit(f"Missing {tips_path}")

    conn = sqlite3.connect(DB_PATH)
    ensure_hikes_schema(conn)
    conn.close()

    ids = fetch_pending_ids(args.limit)
    if not ids:
        print("No pending hikes to enrich.", flush=True)
        print_stats()
        return

    worker_count = default_workers(args.workers)
    print(f"Enriching {len(ids)} hikes (workers={worker_count})…", flush=True)

    if args.dry_run:
        for hid in ids[:25]:
            print(f"  would enrich: {hid}")
        if len(ids) > 25:
            print(f"  … and {len(ids) - 25} more")
        return

    done = 0
    failed = 0
    if worker_count == 1:
        _init_worker(tips_path)
        for i, hid in enumerate(ids, start=1):
            oid, ok, msg = _enrich_hike_task(hid)
            if ok and msg not in ("skipped",):
                done += 1
            elif not ok:
                failed += 1
                print(f"  skip {oid}: {msg}", flush=True)
            if args.progress or i % 5 == 0 or i == len(ids):
                print(f"  {i}/{len(ids)} — {msg}", flush=True)
    else:
        _init_worker(tips_path)
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(_enrich_hike_task, hid): hid for hid in ids}
            completed = 0
            for fut in as_completed(futures):
                completed += 1
                oid, ok, msg = fut.result()
                if ok and msg != "skipped":
                    done += 1
                elif not ok:
                    failed += 1
                    if failed <= 25 or failed % 40 == 0:
                        print(f"  skip {oid}: {msg}", flush=True)
                if args.progress or completed % 20 == 0 or completed == len(ids):
                    print(f"  {completed}/{len(ids)} — last: {msg}", flush=True)

    print(f"Done. Enriched {done} this run ({failed} failed).", flush=True)
    print_stats()


if __name__ == "__main__":
    main()
