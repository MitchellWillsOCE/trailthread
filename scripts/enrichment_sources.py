#!/usr/bin/env python3
"""
Alternate enrichment sources (lower rate-limit pressure than Wikipedia alone).

Sources used:
  - Wikidata (search + claims: image P18, country P17, enwiki sitelink)
  - DBpedia JSON-LD (abstract + thumbnail from Wikipedia slug)
  - OpenStreetMap Nominatim reverse (wikipedia / wikidata tags)
  - Wikipedia REST summary (only when sitelink known — avoids geosearch)
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "Trailthread/1.0 (Europe catalog enrichment; contact: local-dev)"

# Per-host minimum interval (seconds)
_HOST_DELAYS = {
    "wikidata.org": 0.55,
    "dbpedia.org": 0.48,
    "wikipedia.org": 0.75,
    "wikimedia.org": 0.55,
    "openstreetmap.org": 1.1,
}
_last_request: dict[str, float] = {}
_host_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _host_key(host: str) -> str:
    for h in _HOST_DELAYS:
        if h in host:
            return h
    return host


def _host_lock(key: str) -> threading.Lock:
    with _locks_guard:
        if key not in _host_locks:
            _host_locks[key] = threading.Lock()
        return _host_locks[key]


def _throttle(host: str) -> None:
    key = _host_key(host)
    wait = _HOST_DELAYS.get(key, 0.5)
    lock = _host_lock(key)
    with lock:
        now = time.time()
        elapsed = now - _last_request.get(key, 0.0)
        if elapsed < wait:
            time.sleep(wait - elapsed)
        _last_request[key] = time.time()


def http_get_json(url: str, *, timeout: float = 40.0, retries: int = 7) -> dict | list:
    host = urllib.parse.urlparse(url).netloc
    key = _host_key(host)
    wait = _HOST_DELAYS.get(key, 0.5)
    lock = _host_lock(key)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with lock:
                now = time.time()
                elapsed = now - _last_request.get(key, 0.0)
                if elapsed < wait:
                    time.sleep(wait - elapsed)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                _last_request[key] = time.time()
                return payload
        except urllib.error.HTTPError as err:
            last_err = err
            if err.code in (429, 503, 502):
                time.sleep(min(120, 4 * (2**attempt)))
                continue
            if err.code == 404:
                return {}
            raise
        except OSError as err:
            last_err = err
            time.sleep(min(30, 2 + attempt * 2))
    raise RuntimeError(f"GET failed for {url}: {last_err}")


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def commons_file_url(filename: str, *, width: int = 900) -> str:
    name = (filename or "").strip().replace(" ", "_")
    if not name:
        return ""
    if name.lower().startswith("http"):
        return normalize_photo_url(name)
    encoded = urllib.parse.quote(name, safe="")
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}?width={width}"


def normalize_photo_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http://upload.wikimedia.org/") or u.startswith("http://commons.wikimedia.org/"):
        u = "https://" + u[7:]
    return u


def dedupe_photos(photos: list[dict], *, cap: int = 8) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for entry in photos:
        url = normalize_photo_url(entry.get("url", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        item = {**entry, "url": url}
        if not item.get("caption"):
            item["caption"] = ""
        out.append(item)
        if len(out) >= cap:
            break
    return out


@dataclass
class PlaceBundle:
    """Merged facts from multiple providers."""

    wikidata_id: str = ""
    wikipedia_title: str = ""
    description: str = ""
    extract: str = ""
    photos: list[dict] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)


def _pick_wikidata_entity(entities: list[dict], name: str, country: str, lat: float, lng: float) -> str | None:
    name_l = name.lower()
    country_l = (country or "").lower()
    best_id = None
    best_score = -1.0
    for ent in entities:
        item_id = ent.get("id")
        if not item_id:
            continue
        label = (ent.get("label") or "").lower()
        desc = (ent.get("description") or "").lower()
        score = 0.0
        if label == name_l:
            score += 8
        elif name_l in label or label in name_l:
            score += 4
        if country_l and country_l in desc:
            score += 3
        if "city" in desc or "town" in desc or "capital" in desc:
            score += 2
        if "commune" in desc or "municipality" in desc:
            score += 1
        if score > best_score:
            best_score = score
            best_id = item_id
    return best_id


def wikidata_lookup(name: str, country: str, lat: float, lng: float) -> PlaceBundle:
    bundle = PlaceBundle()
    search = urllib.parse.urlencode(
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "limit": 7,
            "format": "json",
        }
    )
    data = http_get_json(f"https://www.wikidata.org/w/api.php?{search}")
    entities = data.get("search", []) if isinstance(data, dict) else []
    item_id = _pick_wikidata_entity(entities, name, country, lat, lng)
    if not item_id:
        return bundle

    bundle.wikidata_id = item_id
    bundle.sources_used.append("wikidata")

    props = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": item_id,
            "props": "labels|descriptions|claims|sitelinks",
            "languages": "en",
            "format": "json",
        }
    )
    detail = http_get_json(f"https://www.wikidata.org/w/api.php?{props}")
    entity = (detail.get("entities") or {}).get(item_id) or {}

    descs = entity.get("descriptions") or {}
    bundle.description = (descs.get("en") or {}).get("value", "").strip()

    claims = entity.get("claims") or {}
    p18 = claims.get("P18") or []
    if p18:
        mainsnak = p18[0].get("mainsnak") or {}
        filename = (mainsnak.get("datavalue") or {}).get("value")
        if isinstance(filename, str) and filename:
            url = commons_file_url(filename)
            if url:
                bundle.photos.append(
                    {"url": url, "caption": name, "source": "Wikidata Commons"}
                )

    sitelinks = entity.get("sitelinks") or {}
    enwiki = sitelinks.get("enwiki") or {}
    wiki_title = enwiki.get("title") or ""
    if wiki_title:
        bundle.wikipedia_title = wiki_title.replace("_", " ")

    return bundle


def dbpedia_from_wikipedia_title(title: str) -> tuple[str, list[dict]]:
    if not title:
        return "", []
    slug = title.replace(" ", "_")
    encoded = urllib.parse.quote(slug, safe="")
    try:
        data = http_get_json(f"https://dbpedia.org/data/{encoded}.json")
    except Exception:
        return "", []

    abstract = ""
    photos: list[dict] = []

    for key, val in data.items():
        if key.endswith("/abstract") and isinstance(val, list):
            for item in val:
                if (item.get("lang") or item.get("@language")) == "en":
                    abstract = strip_html(item.get("value") or "")
                    break
        if key.endswith("/thumbnail") and isinstance(val, list):
            for item in val:
                thumb = item.get("value") or ""
                if thumb:
                    photos.append(
                        {
                            "url": normalize_photo_url(thumb),
                            "caption": title,
                            "source": "DBpedia",
                        }
                    )
                    break
    return abstract, photos


def nominatim_wikipedia_title(lat: float, lng: float) -> str:
    params = urllib.parse.urlencode(
        {
            "format": "json",
            "lat": str(lat),
            "lon": str(lng),
            "zoom": "14",
            "addressdetails": "0",
        }
    )
    try:
        data = http_get_json(f"https://nominatim.openstreetmap.org/reverse?{params}")
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    extra = data.get("extratags") or {}
    wiki = extra.get("wikipedia") or extra.get("wikidata") or ""
    if wiki.startswith("en:"):
        return wiki[3:].replace("_", " ")
    name = data.get("name") or ""
    return name


def wikipedia_summary(title: str) -> dict:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    try:
        data = http_get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}")
    except Exception:
        return {}
    extract = strip_html(data.get("extract_html") or data.get("extract") or "")
    thumb = (data.get("thumbnail") or {}).get("source") or ""
    return {
        "extract": extract,
        "description": (data.get("description") or "").strip(),
        "title": data.get("title") or title,
        "thumbnail": thumb,
    }


def merge_city_bundle(
    name: str,
    country: str,
    lat: float,
    lng: float,
    *,
    use_commons_geosearch: bool = False,
    commons_collector=None,
) -> PlaceBundle:
    """Aggregate text and images from Wikidata → DBpedia → Nominatim → Wikipedia."""
    out = PlaceBundle()
    wd = wikidata_lookup(name, country, lat, lng)
    out.wikidata_id = wd.wikidata_id
    out.wikipedia_title = wd.wikipedia_title
    out.description = wd.description
    out.photos.extend(wd.photos)
    out.sources_used.extend(wd.sources_used)

    wiki_title = out.wikipedia_title
    if not wiki_title:
        wiki_title = nominatim_wikipedia_title(lat, lng)
        if wiki_title:
            out.wikipedia_title = wiki_title
            if "nominatim" not in out.sources_used:
                out.sources_used.append("nominatim")

    if wiki_title:
        abstract, db_photos = dbpedia_from_wikipedia_title(wiki_title)
        if abstract:
            out.extract = abstract
            if "dbpedia" not in out.sources_used:
                out.sources_used.append("dbpedia")
        out.photos.extend(db_photos)

        if len(out.extract) < 120:
            summary = wikipedia_summary(wiki_title)
            if summary.get("extract"):
                out.extract = summary["extract"]
                if "wikipedia" not in out.sources_used:
                    out.sources_used.append("wikipedia")
            if not out.description and summary.get("description"):
                out.description = summary["description"]
            thumb = summary.get("thumbnail")
            if thumb:
                out.photos.append(
                    {"url": normalize_photo_url(thumb), "caption": name, "source": "Wikipedia"}
                )

    if use_commons_geosearch and commons_collector:
        try:
            extra = commons_collector(name, country, lng, lat)[:4]
            out.photos.extend(extra)
            out.sources_used.append("commons")
        except Exception:
            pass

    out.photos = dedupe_photos(out.photos, cap=8)
    return out


def merge_trail_bundle(
    name: str,
    country: str,
    lat: float,
    lng: float,
    *,
    trail_collector=None,
) -> PlaceBundle:
    out = PlaceBundle()
    wd = wikidata_lookup(name, country, lat, lng)
    out.wikipedia_title = wd.wikipedia_title
    out.description = wd.description
    out.photos.extend(wd.photos)
    out.sources_used.extend(wd.sources_used)

    wiki_title = out.wikipedia_title or nominatim_wikipedia_title(lat, lng)
    if wiki_title:
        abstract, db_photos = dbpedia_from_wikipedia_title(wiki_title)
        if abstract:
            out.extract = abstract
            out.sources_used.append("dbpedia")
        out.photos.extend(db_photos)
        if len(out.extract) < 100:
            summary = wikipedia_summary(wiki_title)
            if summary.get("extract"):
                out.extract = summary["extract"]
                out.sources_used.append("wikipedia")
            thumb = summary.get("thumbnail")
            if thumb:
                out.photos.append(
                    {"url": normalize_photo_url(thumb), "caption": name, "source": "Wikipedia"}
                )

    if trail_collector:
        try:
            out.photos.extend(trail_collector(name, country, lng, lat, limit=5))
            out.sources_used.append("commons-trail")
        except Exception:
            pass

    out.photos = dedupe_photos(out.photos, cap=8)
    return out
