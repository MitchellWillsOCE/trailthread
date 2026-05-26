#!/usr/bin/env python3
"""Promote *.db.new builds, drop SQLite WAL sidecars, and remove stale temp DBs."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = [
    ROOT / "Trip" / "cities" / "cities.db",
    ROOT / "Trip" / "parks" / "parks.db",
    ROOT / "Trip" / "hikes" / "hikes.db",
    ROOT / "Trip" / "poi" / "poi.db",
]


def checkpoint(path: Path) -> None:
    if not path.is_file():
        return
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def remove_sidecars(base: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(base) + suffix)
        if sidecar.is_file():
            sidecar.unlink(missing_ok=True)


def promote_new(base: Path) -> bool:
    new_path = Path(f"{base}.new")
    if not new_path.is_file():
        return False
    use_new = not base.is_file()
    if base.is_file() and new_path.stat().st_mtime >= base.stat().st_mtime:
        use_new = True
    if not use_new:
        new_path.unlink(missing_ok=True)
        print(f"  kept {base.name} (newer than .new)")
        return False

    remove_sidecars(base)
    if base.is_file():
        base.unlink()
    os.replace(new_path, base)
    print(f"  promoted {new_path.name} -> {base.name}")
    return True


def remove_temps(dir_path: Path) -> None:
    if not dir_path.is_dir():
        return
    for pattern in ("*.build.tmp", "*.db.build.tmp"):
        for tmp in dir_path.glob(pattern):
            tmp.unlink(missing_ok=True)
            print(f"  removed temp {tmp.name}")


def main() -> None:
    print("Consolidating catalog databases…")
    for base in CATALOGS:
        parent = base.parent
        print(f"\n{parent.name}/")
        remove_temps(parent)
        promote_new(base)
        checkpoint(base)
        remove_sidecars(base)

    print("\nDone. APIs should read the primary .db files only.")


if __name__ == "__main__":
    main()
