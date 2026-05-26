"""Replace generic activities/tips with category-aware pools.

Walks cities.db, parks.db, poi.db; for any row whose existing
`activities_json` matches the legacy template patterns (or is a
Wikipedia sentence dump), regenerates activities + tips from
`place_activities.py` using the row's `category` (+ `locale` for
cities) and a stable seed from the row id.

Curated activities (e.g. seed entries for Rome, Dubrovnik) are
preserved unless `--force` is passed.

Usage:
    python scripts/apply-place-activities.py            # dry-run summary
    python scripts/apply-place-activities.py --apply    # write changes
    python scripts/apply-place-activities.py --apply --force   # rewrite all
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog_paths import CITIES_DB, PARKS_DB, POI_DB  # noqa: E402
from place_activities import (  # noqa: E402
    city_activities,
    city_tips,
    looks_like_generic_activities,
    park_activities,
    park_tips,
    poi_activities,
    poi_tips,
)

COUNTRY_TIPS_PATH = ROOT / "scripts" / "data" / "country-travel-tips.json"


def load_country_tips() -> dict[str, list[str]]:
    if not COUNTRY_TIPS_PATH.is_file():
        return {}
    try:
        data = json.loads(COUNTRY_TIPS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {k: list(v or []) for k, v in data.items() if isinstance(v, list)}


def _open_writable(primary: Path, *, apply: bool) -> tuple[sqlite3.Connection, Path]:
    """Open the DB read-only for dry-runs; copy to .new for writes if the
    primary is locked by another writer (e.g. an in-flight enrich job)."""
    if not apply:
        conn = sqlite3.connect(f"file:{primary}?mode=ro", uri=True, timeout=2)
        return conn, primary
    new_path = Path(f"{primary}.new")
    if new_path.exists():
        new_path.unlink()
    print(f"  copy -> {new_path.name}", flush=True)
    shutil.copyfile(primary, new_path)
    conn = sqlite3.connect(str(new_path), timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn, new_path


def parse_json_list(blob: str | None) -> list[str]:
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return [str(x) for x in data if isinstance(x, str)]


def update_cities(apply: bool, force: bool, country_tips: dict[str, list[str]]) -> dict:
    conn, used = _open_writable(CITIES_DB, apply=apply)
    try:
        rows = conn.execute(
            """
            SELECT id, name, country, category, locale, activities_json, tips_json
            FROM cities
            """
        ).fetchall()
        print(f"  rows={len(rows)}", flush=True)
        changed = 0
        preserved = 0
        if apply:
            conn.execute("BEGIN")
        for cid, name, country, cat, loc, act_json, tip_json in rows:
            existing = parse_json_list(act_json)
            if not force and not looks_like_generic_activities(existing):
                preserved += 1
                continue
            category = (cat or "town").strip() or "town"
            locale = (loc or "inland").strip() or "inland"
            seed = f"city:{cid or name}"
            new_acts = city_activities(category, locale, seed)
            new_tips = city_tips(
                category, locale, country or "", seed,
                country_tips.get(country or ""),
            )
            if new_acts == existing and new_tips == parse_json_list(tip_json):
                continue
            changed += 1
            if apply:
                conn.execute(
                    "UPDATE cities SET activities_json = ?, tips_json = ? WHERE id = ?",
                    (json.dumps(new_acts, ensure_ascii=False),
                     json.dumps(new_tips, ensure_ascii=False), cid),
                )
        if apply:
            conn.commit()
        return {"total": len(rows), "changed": changed, "preserved": preserved, "path": used}
    finally:
        conn.close()


def update_parks(apply: bool, force: bool) -> dict:
    conn, used = _open_writable(PARKS_DB, apply=apply)
    try:
        rows = conn.execute(
            "SELECT id, name, country, category, activities_json, tips_json FROM parks"
        ).fetchall()
        print(f"  rows={len(rows)}", flush=True)
        changed = 0
        preserved = 0
        if apply:
            conn.execute("BEGIN")
        for pid, name, country, cat, act_json, tip_json in rows:
            existing = parse_json_list(act_json)
            if not force and not looks_like_generic_activities(existing):
                preserved += 1
                continue
            category = (cat or "national-park").strip() or "national-park"
            seed = f"park:{pid or name}"
            new_acts = park_activities(category, seed)
            new_tips = park_tips(category, seed)
            if new_acts == existing and new_tips == parse_json_list(tip_json):
                continue
            changed += 1
            if apply:
                conn.execute(
                    "UPDATE parks SET activities_json = ?, tips_json = ? WHERE id = ?",
                    (json.dumps(new_acts, ensure_ascii=False),
                     json.dumps(new_tips, ensure_ascii=False), pid),
                )
        if apply:
            conn.commit()
        return {"total": len(rows), "changed": changed, "preserved": preserved, "path": used}
    finally:
        conn.close()


def update_pois(apply: bool, force: bool) -> dict:
    conn, used = _open_writable(POI_DB, apply=apply)
    try:
        rows = conn.execute(
            "SELECT id, name, country, category, activities_json, tips_json FROM pois"
        ).fetchall()
        print(f"  rows={len(rows)}", flush=True)
        changed = 0
        preserved = 0
        if apply:
            conn.execute("BEGIN")
        for pid, name, country, cat, act_json, tip_json in rows:
            existing = parse_json_list(act_json)
            if not force and not looks_like_generic_activities(existing):
                preserved += 1
                continue
            category = (cat or "landmark").strip() or "landmark"
            seed = f"poi:{pid or name}"
            new_acts = poi_activities(category, seed)
            new_tips = poi_tips(category, seed)
            if new_acts == existing and new_tips == parse_json_list(tip_json):
                continue
            changed += 1
            if apply:
                conn.execute(
                    "UPDATE pois SET activities_json = ?, tips_json = ? WHERE id = ?",
                    (json.dumps(new_acts, ensure_ascii=False),
                     json.dumps(new_tips, ensure_ascii=False), pid),
                )
        if apply:
            conn.commit()
        return {"total": len(rows), "changed": changed, "preserved": preserved, "path": used}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--force", action="store_true",
        help="Rewrite even rows that currently look hand-curated.",
    )
    args = parser.parse_args()

    country_tips = load_country_tips()

    print("cities:")
    s = update_cities(args.apply, args.force, country_tips)
    print(f"  total={s['total']} changed={s['changed']} preserved-curated={s['preserved']} ({s['path'].name})")

    print("parks:")
    s = update_parks(args.apply, args.force)
    print(f"  total={s['total']} changed={s['changed']} preserved-curated={s['preserved']} ({s['path'].name})")

    print("pois:")
    s = update_pois(args.apply, args.force)
    print(f"  total={s['total']} changed={s['changed']} preserved-curated={s['preserved']} ({s['path'].name})")

    if not args.apply:
        print("\n(dry-run — pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
