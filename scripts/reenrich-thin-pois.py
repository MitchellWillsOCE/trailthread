"""Re-enrich POIs whose photo count is below a threshold.

Used to boost coverage on landmarks where the first enrichment pass
returned only one or two photos. Re-runs the standard photo + summary
fetch with `photo_mode='full'` and writes back to the catalog DB.

Usage:
    python scripts/reenrich-thin-pois.py --threshold 4 --limit 25
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from catalog_paths import POI_DB  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _open_writable(primary: Path) -> tuple[sqlite3.Connection, Path]:
    new_path = Path(f"{primary}.new")
    if new_path.exists():
        new_path.unlink()
    print(f"  copy -> {new_path.name}", flush=True)
    shutil.copyfile(primary, new_path)
    conn = sqlite3.connect(str(new_path), timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn, new_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="0 = all matching")
    parser.add_argument("--country", type=str, default="")
    parser.add_argument("--sleep", type=float, default=1.5)
    args = parser.parse_args()

    enrich_mod = _load_module(
        "enrich_poi_db",
        ROOT / "scripts" / "enrich-poi-db.py",
    )
    photos_mod = enrich_mod.load_photos_mod()
    tips_path = ROOT / "scripts" / "data" / "country-travel-tips.json"
    tips_db = json.loads(tips_path.read_text(encoding="utf-8"))

    conn, used = _open_writable(POI_DB)
    try:
        rows = conn.execute(
            "SELECT * FROM pois ORDER BY popularity DESC"
        ).fetchall()
        thin: list[dict] = []
        for row_obj in rows:
            row = {k: row_obj[k] for k in row_obj.keys()}
            if args.country and (row.get("country") or "").lower() != args.country.lower():
                continue
            photos = json.loads(row.get("photos_json") or "[]")
            if len(photos) < args.threshold:
                row["__current_photos"] = len(photos)
                thin.append(row)
        if args.limit:
            thin = thin[: args.limit]
        print(f"  candidates: {len(thin)}")
        if not thin:
            return 0

        for i, row in enumerate(thin, start=1):
            name = row["name"] or "?"
            current = row["__current_photos"]
            print(
                f"  [{i}/{len(thin)}] {name.encode('ascii','replace').decode('ascii')} "
                f"({row.get('country')}) — currently {current} photos",
                flush=True,
            )
            try:
                payload = enrich_mod.enrich_poi(row, photos_mod, tips_db)
            except Exception as e:
                print(f"    skipped ({e})", flush=True)
                continue

            new_photos = json.loads(payload.get("photos_json") or "[]")
            # Preserve old photos as a fallback if the new pass returned fewer.
            if len(new_photos) < current:
                old_photos = json.loads(row.get("photos_json") or "[]")
                # Merge: new ones first (likely better), then any old not duplicated.
                seen = {p.get("url") for p in new_photos if p.get("url")}
                for p in old_photos:
                    if p.get("url") and p["url"] not in seen:
                        new_photos.append(p)
                payload["photos_json"] = json.dumps(new_photos[:8], ensure_ascii=False)
                # Also rebuild highlights from merged photos
                highlights = []
                for entry in new_photos[:4]:
                    cap = entry.get("caption") or name
                    highlights.append({"title": cap[:48], "caption": cap, "image": entry.get("url")})
                payload["highlights_json"] = json.dumps(highlights, ensure_ascii=False)
                payload["enriched"] = 1 if new_photos else 0

            conn.execute(
                """
                UPDATE pois SET
                    summary = ?, tagline = ?, activities_json = ?, tips_json = ?,
                    photos_json = ?, highlights_json = ?, enriched = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    payload["summary"],
                    payload["tagline"],
                    payload["activities_json"],
                    payload["tips_json"],
                    payload["photos_json"],
                    payload["highlights_json"],
                    payload["enriched"],
                    row["id"],
                ),
            )
            print(
                f"    -> {len(json.loads(payload['photos_json']))} photos",
                flush=True,
            )
            time.sleep(args.sleep)

        conn.commit()
    finally:
        conn.close()
    print(f"\nWrote {used.name}. Run consolidate-catalog-dbs.py to promote.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
