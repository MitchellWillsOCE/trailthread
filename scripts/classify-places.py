"""Add `category` + `locale` columns to catalog DBs and populate them.

* `cities.db.cities`  → `category` (capital/metropolis/.../hamlet) and
                        `locale` (coastal/island/mountain/.../inland)
* `parks.db.parks`    → `category` (national-park/marine-park/...)
* `poi.db.pois`       → refines `category` (palace/cathedral/...) when
                        the seeded value is broad (`heritage`/`monument`).

Idempotent: safe to re-run after re-enrichment. Writes a `.new`
sibling DB if the primary file is locked by the dev server, mirroring
the convention used elsewhere in this repo.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog_paths import CITIES_DB, PARKS_DB, POI_DB  # noqa: E402
from place_categories import (  # noqa: E402
    HIGHLY_SPECIFIC_POI_CATEGORIES,
    classify_city,
    classify_park,
    classify_poi,
)

POI_SEED_PATH = ROOT / "scripts" / "data" / "europe-poi-seed.json"


def reseed_poi_categories(conn: sqlite3.Connection, apply: bool) -> int:
    """Restore POI `category` values from the curated seed JSON.

    The seed is the source of truth for hand-picked classifications
    (fortress/palace/etc.); reseeding undoes any past run that
    accidentally demoted a curated value via name-based regex.
    """
    import json

    if not POI_SEED_PATH.is_file():
        return 0
    seed = json.loads(POI_SEED_PATH.read_text(encoding="utf-8"))
    fixed = 0
    for entry in seed:
        name = (entry.get("name") or "").strip()
        cat = (entry.get("category") or "").strip().lower()
        if not name or not cat:
            continue
        row = conn.execute(
            "SELECT id, category FROM pois WHERE lower(name) = lower(?) LIMIT 1",
            (name,),
        ).fetchone()
        if not row:
            continue
        pid, current = row
        current_lc = (current or "").lower()
        if current_lc == cat:
            continue
        # If the DB already has a highly-specific value (e.g. `bridge`)
        # don't demote it back to a broader seed value (`monument`).
        if (
            current_lc in HIGHLY_SPECIFIC_POI_CATEGORIES
            and cat not in HIGHLY_SPECIFIC_POI_CATEGORIES
        ):
            continue
        fixed += 1
        if apply:
            conn.execute("UPDATE pois SET category = ? WHERE id = ?", (cat, pid))
    if apply:
        conn.commit()
    return fixed


def _open_writable(primary: Path) -> tuple[sqlite3.Connection, Path]:
    """Open the primary DB for write; fall back to copying to `.new`
    when the primary is locked (Vite dev server has a file handle on
    Windows)."""
    try:
        conn = sqlite3.connect(str(primary))
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        return conn, primary
    except sqlite3.OperationalError:
        new_path = Path(f"{primary}.new")
        shutil.copyfile(primary, new_path)
        conn = sqlite3.connect(str(new_path))
        return conn, new_path


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(
    conn: sqlite3.Connection, table: str, name: str, ddl: str, apply: bool
) -> bool:
    cols = _columns(conn, table)
    if name in cols:
        return False
    if apply:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    return True


def classify_cities(apply: bool) -> tuple[int, int, Path]:
    conn, used_path = _open_writable(CITIES_DB)
    try:
        added_cat = _ensure_column(conn, "cities", "category", "category TEXT DEFAULT ''", apply)
        added_loc = _ensure_column(conn, "cities", "locale",   "locale TEXT DEFAULT ''", apply)
        if added_cat or added_loc:
            verb = "added" if apply else "would add"
            print(f"  cities: {verb} columns (category={added_cat}, locale={added_loc})")

        cols = _columns(conn, "cities")
        cat_expr = "category" if "category" in cols else "'' AS category"
        loc_expr = "locale" if "locale" in cols else "'' AS locale"
        rows = conn.execute(
            f"SELECT id, name, cc, pop, lat, lng, {cat_expr}, {loc_expr} FROM cities"
        ).fetchall()

        changed = 0
        for cid, name, cc, pop, lat, lng, cur_cat, cur_loc in rows:
            new_cat, new_loc = classify_city(
                name=name or "", cc=cc, pop=pop, lat=lat, lng=lng
            )
            if new_cat == (cur_cat or "") and new_loc == (cur_loc or ""):
                continue
            changed += 1
            if apply:
                conn.execute(
                    "UPDATE cities SET category = ?, locale = ? WHERE id = ?",
                    (new_cat, new_loc, cid),
                )

        if apply:
            conn.commit()
        return len(rows), changed, used_path
    finally:
        conn.close()


def classify_parks(apply: bool) -> tuple[int, int, Path]:
    conn, used_path = _open_writable(PARKS_DB)
    try:
        added = _ensure_column(conn, "parks", "category", "category TEXT DEFAULT ''", apply)
        if added:
            verb = "added" if apply else "would add"
            print(f"  parks: {verb} column category")

        cols = _columns(conn, "parks")
        cat_expr = "category" if "category" in cols else "'' AS category"
        rows = conn.execute(
            f"SELECT id, name, area_km2, lat, lng, iucn_category, {cat_expr} FROM parks"
        ).fetchall()

        changed = 0
        for pid, name, area, lat, lng, iucn, cur_cat in rows:
            new_cat = classify_park(
                name=name or "",
                area_km2=area,
                lat=lat,
                lng=lng,
                iucn_category=iucn,
                existing_category=cur_cat,
            )
            if new_cat == (cur_cat or ""):
                continue
            changed += 1
            if apply:
                conn.execute(
                    "UPDATE parks SET category = ? WHERE id = ?", (new_cat, pid)
                )

        if apply:
            conn.commit()
        return len(rows), changed, used_path
    finally:
        conn.close()


def classify_pois(apply: bool) -> tuple[int, int, Path]:
    conn, used_path = _open_writable(POI_DB)
    try:
        restored = reseed_poi_categories(conn, apply)
        if restored:
            verb = "restored" if apply else "would restore"
            print(f"  pois: {verb} {restored} category(s) from seed")
        rows = conn.execute("SELECT id, name, category FROM pois").fetchall()

        changed = 0
        for pid, name, cur_cat in rows:
            new_cat = classify_poi(name=name or "", existing_category=cur_cat)
            if new_cat == (cur_cat or ""):
                continue
            changed += 1
            if apply:
                conn.execute(
                    "UPDATE pois SET category = ? WHERE id = ?", (new_cat, pid)
                )

        if apply:
            conn.commit()
        return len(rows), changed, used_path
    finally:
        conn.close()


def histogram(conn_path: Path, table: str, columns: list[str]) -> None:
    conn = sqlite3.connect(str(conn_path))
    try:
        for col in columns:
            rows = conn.execute(
                f"SELECT {col}, COUNT(*) FROM {table} GROUP BY {col} ORDER BY COUNT(*) DESC"
            ).fetchall()
            label = ", ".join(f"{v or '∅'}={n}" for v, n in rows)
            print(f"    {col}: {label}")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes")
    parser.add_argument(
        "--stats", action="store_true", help="print category histograms"
    )
    args = parser.parse_args()

    print("cities:")
    n, c, p = classify_cities(args.apply)
    print(f"  {c}/{n} rows would change ({p.name})")
    if args.stats:
        histogram(p, "cities", ["category", "locale"])

    print("parks:")
    n, c, p = classify_parks(args.apply)
    print(f"  {c}/{n} rows would change ({p.name})")
    if args.stats:
        histogram(p, "parks", ["category"])

    print("pois:")
    n, c, p = classify_pois(args.apply)
    print(f"  {c}/{n} rows would change ({p.name})")
    if args.stats:
        histogram(p, "pois", ["category"])

    if not args.apply:
        print("\n(dry-run — re-run with --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
