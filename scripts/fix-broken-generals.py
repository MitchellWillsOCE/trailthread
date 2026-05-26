#!/usr/bin/env python3
"""Fix a small set of cities with truncated general text (Wikipedia-only, one at a time)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
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
USER_AGENT = "Trailthread/1.0 (city copy repair)"


def wiki_extract(name: str, country: str) -> str:
    params = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": f"{name}, {country}",
            "limit": 1,
            "namespace": 0,
            "format": "json",
        }
    )
    req = urllib.request.Request(
        f"https://en.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    titles = data[1] if isinstance(data, list) and len(data) > 1 else []
    if not titles:
        return ""
    title = titles[0]
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    req2 = urllib.request.Request(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req2, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return src.strip_html(payload.get("extract_html") or payload.get("extract") or "")


def rebuild_activities(general: str, name: str) -> list[str]:
    out: list[str] = []
    for sentence in sentences(general)[1:12]:
        line = highlight_line(sentence, 120)
        if line and line not in out:
            out.append(line)
        if len(out) >= 3:
            break
    defaults = [
        f"Stroll the historic centre of {name}",
        "Find a local café or market",
        "Catch sunset from a viewpoint",
    ]
    for d in defaults:
        if len(out) >= 3:
            break
        if d not in out:
            out.append(d)
    return out[:3]


def main() -> None:
    configure_stdio()
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")
    rows = conn.execute(
        "SELECT id, name, country, lat, lng, general FROM cities WHERE source != 'trip'"
    ).fetchall()
    targets = [r for r in rows if is_broken_copy(r[5] or "")]
    print(f"Fixing {len(targets)} cities…", flush=True)
    fixed = 0
    for city_id, name, country, lat, lng, general in targets:
        time.sleep(1.5)
        try:
            extract = wiki_extract(name, country)
        except Exception as err:
            print(f"  skip {name}: {err}", flush=True)
            continue
        if not extract:
            continue
        new_gen = summary_paragraph(extract, 420)
        if not new_gen or is_broken_copy(new_gen):
            continue
        new_tag = complete_phrase(extract.split(". ")[0] + ".", 88)
        new_act = json.dumps(rebuild_activities(new_gen, name), ensure_ascii=False)
        for attempt in range(8):
            try:
                conn.execute(
                    "UPDATE cities SET tagline = ?, general = ?, activities_json = ?, updated_at = datetime('now') WHERE id = ?",
                    (new_tag, new_gen, new_act, city_id),
                )
                conn.commit()
                break
            except sqlite3.OperationalError as err:
                if "locked" not in str(err).lower() or attempt == 7:
                    raise
                time.sleep(3)
        fixed += 1
        print(f"  fixed: {name}", flush=True)
    conn.close()
    print(f"Done. {fixed}/{len(targets)} updated.", flush=True)


if __name__ == "__main__":
    main()
