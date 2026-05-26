"""Common helpers shared across the data-pipeline scripts.

Centralises trivially-duplicated utilities so each script doesn't
re-implement them. Existing scripts can opt in incrementally by adding
``from _common import configure_stdio`` etc.; the legacy copies remain
backward-compatible until they're removed.
"""
from __future__ import annotations

import math
import re
import shutil
import sqlite3
import sys
from pathlib import Path


def configure_stdio() -> None:
    """Force UTF-8 stdout/stderr so Windows cp1252 doesn't crash on
    non-ASCII place names (Plitvička, Žabljak, …)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def strip_html(text: str) -> str:
    """Return *text* with HTML tags removed and whitespace stripped."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres between (lng, lat) tuples.

    Note: pairs are (lng, lat) for consistency with GeoJSON coordinate ordering;
    matches the convention used by ``build-hikes-db.py``.
    """
    lat1, lng1 = math.radians(a[1]), math.radians(a[0])
    lat2, lng2 = math.radians(b[1]), math.radians(b[0])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def bbox_from_point(
    lat: float, lng: float, km: float = 6.0
) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) bounds *km* kilometres from a point."""
    dlat = km / 111.0
    dlng = km / (111.0 * max(0.35, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def title_from_activity(text: str, max_len: int = 42) -> str:
    """Trim an activity sentence into a short title."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t.rstrip(".")
    cut = t[:max_len]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 20 else cut).strip().rstrip(".,")


def open_writable(primary: Path) -> tuple[sqlite3.Connection, Path]:
    """Open *primary* for writing; if it's locked (Vite dev server holds an
    fd on Windows) copy to ``<primary>.new`` and write there. Callers should
    swap the .new sibling back over once they're done.

    Returns ``(connection, actual_path)``.
    """
    primary = Path(primary)
    try:
        conn = sqlite3.connect(str(primary), timeout=2)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn, primary
    except sqlite3.OperationalError:
        new_path = Path(f"{primary}.new")
        if new_path.exists():
            new_path.unlink()
        print(f"  copy -> {new_path.name}", flush=True)
        shutil.copyfile(primary, new_path)
        conn = sqlite3.connect(str(new_path), timeout=10)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn, new_path


def safe_wiki_search(photos_mod, query: str, *, limit: int = 3) -> list[dict]:
    """Wikipedia text search that never raises — returns [] on failure."""
    try:
        return photos_mod.wiki_text_search(query, limit=limit)
    except Exception:
        return []


def safe_geosearch(
    photos_mod, lat: float, lng: float, *, limit: int = 6, radius_m: int = 12_000
) -> list[dict]:
    """Wikipedia geo search that never raises — returns [] on failure."""
    try:
        return photos_mod.wiki_geosearch(lat, lng, radius_m=radius_m, limit=limit)
    except Exception:
        return []
