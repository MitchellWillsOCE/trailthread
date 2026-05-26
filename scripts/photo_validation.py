#!/usr/bin/env python3
"""Verify and normalize city/trail photo URLs for browser-safe display."""

from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "Trailthread/1.0 (photo validation)"
_validate_lock = threading.Lock()
_last_validate = 0.0

# Lazy-load Commons helpers from fetch-location-photos.py
_photos_mod = None


def _photos_module():
    global _photos_mod
    if _photos_mod is None:
        path = ROOT / "scripts" / "fetch-location-photos.py"
        spec = importlib.util.spec_from_file_location("fetch_photos", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _photos_mod = mod
    return _photos_mod


def normalize_photo_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http://upload.wikimedia.org/") or u.startswith("http://commons.wikimedia.org/"):
        u = "https://" + u[7:]
    if u.startswith("./Trip/"):
        u = u[2:]
    if u.startswith("Trip/"):
        u = "/" + u
    return u


def _looks_like_image(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    return False


def _filename_from_commons_filepath(url: str) -> str | None:
    if "Special:FilePath/" not in url:
        return None
    part = url.split("Special:FilePath/", 1)[1]
    part = part.split("?", 1)[0]
    return urllib.parse.unquote(part).replace("_", " ")


def resolve_direct_image_url(url: str, *, timeout: float = 20.0) -> str:
    """Prefer stable upload.wikimedia.org thumb URLs over Special:FilePath redirects."""
    url = normalize_photo_url(url)
    if not url:
        return ""

    if url.startswith("/Trip/") or url.startswith("./Trip/"):
        local = ROOT / url.lstrip("/")
        return url if local.is_file() else ""

    if "upload.wikimedia.org" in url:
        return url

    filename = _filename_from_commons_filepath(url)
    if filename:
        try:
            mod = _photos_module()
            batch = mod.wiki_batch_files([f"File:{filename.replace(' ', '_')}"])
            if batch and batch[0].get("url"):
                return normalize_photo_url(batch[0]["url"])
        except Exception:
            pass

    return url


def is_trusted_cdn_image_url(url: str) -> bool:
    """upload.wikimedia.org thumbs are browser-safe once stored at a valid size."""
    if not url.startswith("https://upload.wikimedia.org/"):
        return False
    return bool(
        re.search(
            r"/(?:commons/)?thumb/|/wikipedia/(?:commons|en)/",
            url,
            re.I,
        )
        and re.search(r"\.(?:jpg|jpeg|png|webp|gif)(?:/|\?|$)", url, re.I)
    )


def photo_url_is_viewable(url: str, *, timeout: float = 18.0) -> bool:
    """True when the URL responds with image bytes (not HTML error pages)."""
    resolved = resolve_direct_image_url(url, timeout=timeout)
    if not resolved:
        return False

    if resolved.startswith("/Trip/"):
        local = ROOT / resolved.lstrip("/")
        return local.is_file() and local.stat().st_size > 400

    if is_trusted_cdn_image_url(resolved):
        return True

    if not resolved.startswith("http"):
        return False

    headers = {"User-Agent": USER_AGENT, "Range": "bytes=0-8191", "Accept": "image/*,*/*"}
    for attempt in range(4):
        try:
            global _last_validate
            with _validate_lock:
                wait = 0.35 - (time.time() - _last_validate)
                if wait > 0:
                    time.sleep(wait)
                _last_validate = time.time()
            req = urllib.request.Request(resolved, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status not in (200, 206):
                    return False
                ct = (resp.headers.get("Content-Type") or "").lower()
                if "text/html" in ct or "application/json" in ct:
                    return False
                chunk = resp.read(8192)
                if len(chunk) < 80:
                    return False
                if ct.startswith("image/") or "webp" in ct or "octet-stream" in ct:
                    return _looks_like_image(chunk) or len(chunk) > 500
                return _looks_like_image(chunk)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return False
            if err.code == 416:
                return True
            if err.code == 429 and attempt < 3:
                time.sleep(min(30, 4 * (attempt + 1)))
                continue
            return False
        except Exception:
            return False
    return False


def normalize_photo_entry(entry: dict, *, name: str = "") -> dict | None:
    if not entry:
        return None
    raw_url = entry.get("url") or entry.get("src") or ""
    direct = resolve_direct_image_url(raw_url)
    if not direct:
        return None
    if not photo_url_is_viewable(direct):
        return None
    caption = (entry.get("caption") or name or "").strip()
    out = {"url": direct, "caption": caption}
    if entry.get("source"):
        out["source"] = entry["source"]
    return out


def filter_viewable_photos(photos: list, *, cap: int = 8, name: str = "") -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for entry in photos or []:
        if isinstance(entry, str):
            entry = {"url": entry, "caption": name}
        normalized = normalize_photo_entry(entry, name=name)
        if not normalized:
            continue
        url = normalized["url"]
        if url in seen:
            continue
        seen.add(url)
        out.append(normalized)
        if len(out) >= cap:
            break
    return out


def parse_photos_json(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
