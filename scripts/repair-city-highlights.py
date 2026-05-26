#!/usr/bin/env python3
"""Rebuild city copy from full sentences (no mid-sentence cuts)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio  # noqa: E402
import enrichment_sources as src  # noqa: E402
from text_phrase import (  # noqa: E402
    complete_phrase,
    highlight_line,
    is_broken_copy,
    sentences,
    summary_paragraph,
)

DB = ROOT / "Trip" / "cities" / "cities.db"
HIGHLIGHT_MAX = 120
TAGLINE_MAX = 88


def default_activities(name: str) -> list[str]:
    return [
        f"Stroll the historic centre of {name}",
        "Find a local café or market",
        "Catch sunset from a viewpoint",
    ]


def rebuild_activities(general: str, name: str) -> list[str]:
    out: list[str] = []
    for sentence in sentences(general)[1:12]:
        line = highlight_line(sentence, HIGHLIGHT_MAX)
        if line and line not in out:
            out.append(line)
        if len(out) >= 3:
            break
    for fallback in default_activities(name):
        if len(out) >= 3:
            break
        if fallback not in out:
            out.append(fallback)
    return out[:3]


def _wiki_summary_extract(title: str) -> str:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    data = src.http_get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}")
    return src.strip_html(data.get("extract_html") or data.get("extract") or "")


def refetch_general(name: str, country: str, lat: float, lng: float) -> str:
    """Wikipedia summary only (lighter than full Wikidata merge)."""
    try:
        search = urllib.parse.urlencode(
            {
                "action": "opensearch",
                "search": f"{name}, {country}",
                "limit": 1,
                "namespace": 0,
                "format": "json",
            }
        )
        data = src.http_get_json(f"https://en.wikipedia.org/w/api.php?{search}")
        titles = data[1] if isinstance(data, list) and len(data) > 1 else []
        title = titles[0] if titles else ""
        if not title:
            return ""
        extract = _wiki_summary_extract(title)
        return summary_paragraph(extract, 420) if extract else ""
    except Exception:
        return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refetch-broken", action="store_true", help="Re-query Wikipedia for corrupted general text")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    configure_stdio()

    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    rows = conn.execute(
        "SELECT id, name, country, lat, lng, tagline, general, activities_json FROM cities WHERE source != 'trip'"
    ).fetchall()
    if args.refetch_broken:
        rows = [r for r in rows if is_broken_copy(r[6] or "") or "…" in (r[6] or "")]
    if args.limit:
        rows = rows[: args.limit]
    updated = 0
    for city_id, name, country, lat, lng, tagline, general, activities_json in rows:
        new_gen = general
        if args.refetch_broken or is_broken_copy(general or ""):
            fetched = refetch_general(name, country, lat, lng)
            if fetched and not is_broken_copy(fetched):
                new_gen = fetched
            else:
                new_gen = summary_paragraph(general or "", 420)
            time.sleep(1.2)
        else:
            new_gen = summary_paragraph(general or "", 420)

        new_tag = complete_phrase(tagline or "", TAGLINE_MAX)
        new_act = json.dumps(rebuild_activities(new_gen or "", name), ensure_ascii=False)
        changed = new_tag != tagline or new_gen != general or new_act != (activities_json or "[]")
        if not changed:
            continue
        updated += 1
        if args.dry_run:
            print(f"  would fix: {name}", flush=True)
            continue
        conn.execute(
            "UPDATE cities SET tagline = ?, general = ?, activities_json = ?, updated_at = datetime('now') WHERE id = ?",
            (new_tag, new_gen, new_act, city_id),
        )
    if not args.dry_run and updated:
        conn.commit()
    conn.close()
    label = "would update" if args.dry_run else "updated"
    print(f"{label} {updated} cities", flush=True)


if __name__ == "__main__":
    main()
