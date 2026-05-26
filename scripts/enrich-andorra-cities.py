"""Targeted enrichment for Andorra cities (Wikipedia summary + photos).

Reuses `enrich_row_dict` from `enrich-cities-db.py` so the same logic
(merging Wikipedia bundle, generating tagline/general, picking
category-aware activities/tips) runs for the small Andorran roster.

Usage: python scripts/enrich-andorra-cities.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from catalog_paths import CITIES_DB  # noqa: E402

TIPS_PATH = ROOT / "scripts" / "data" / "country-travel-tips.json"


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
    enrich_mod = _load_module(
        "enrich_cities_db",
        ROOT / "scripts" / "enrich-cities-db.py",
    )
    photos_mod = enrich_mod.load_photo_module()
    tips_db = json.loads(TIPS_PATH.read_text(encoding="utf-8"))

    conn, used = _open_writable(CITIES_DB)
    try:
        rows = conn.execute(
            "SELECT * FROM cities WHERE country = 'Andorra' "
            "ORDER BY COALESCE(pop, 0) DESC"
        ).fetchall()
        print(f"  rows={len(rows)}")

        for i, row_obj in enumerate(rows, start=1):
            row = {k: row_obj[k] for k in row_obj.keys()}
            name = row["name"]
            print(f"  [{i}/{len(rows)}] enriching {name.encode('ascii','replace').decode('ascii')}…", flush=True)
            try:
                payload = enrich_mod.enrich_row_dict(row, photos_mod, tips_db, photo_mode="full")
            except Exception as e:
                print(f"    skipped ({e})", flush=True)
                continue
            conn.execute(
                """
                UPDATE cities SET
                    general = ?, tagline = ?, activities_json = ?, tips_json = ?,
                    photos_json = ?, enriched = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    payload["general"],
                    payload["tagline"],
                    payload["activities_json"],
                    payload["tips_json"],
                    payload["photos_json"],
                    payload["enriched"],
                    row["id"],
                ),
            )
            photos = json.loads(payload["photos_json"]) if payload["photos_json"] else []
            print(
                f"    photos={len(photos)} general_len={len(payload['general'] or '')} enriched={payload['enriched']}",
                flush=True,
            )
            time.sleep(1.5)

        conn.commit()
    finally:
        conn.close()
    print(f"\nWrote {used}. Run consolidate-catalog-dbs.py to promote.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
