#!/usr/bin/env python3
"""
Run Europe city + hike enrichment in paced batches (multi-source pipeline).

Uses Wikidata, DBpedia, OSM Nominatim, and Wikipedia only when needed — fewer 429s.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import configure_stdio  # noqa: E402
from catalog_paths import CITIES_DB, HIKES_DB  # noqa: E402


def count_pending(db: Path, table: str) -> tuple[int, int, int]:
    if not db.is_file():
        return 0, 0, 0
    conn = sqlite3.connect(db)
    if table == "cities":
        total = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
        enriched = conn.execute("SELECT COUNT(*) FROM cities WHERE enriched = 1").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM cities WHERE enriched = 0 AND source != 'trip'"
        ).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM hikes").fetchone()[0]
        enriched = conn.execute("SELECT COUNT(*) FROM hikes WHERE COALESCE(enriched, 0) = 1").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM hikes WHERE COALESCE(enriched, 0) = 0").fetchone()[0]
    conn.close()
    return total, enriched, pending


def run(cmd: list[str]) -> int:
    print(f"\n>> {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def resolve_workers(requested: int, *, cap: int) -> int:
    cpus = os.cpu_count() or 4
    if requested > 0:
        return max(1, requested)
    return max(1, min(cpus - 2, cap))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city-batch", type=int, default=600, help="Cities per batch")
    parser.add_argument("--hike-batch", type=int, default=0, help="Hikes per batch (0 = all pending)")
    parser.add_argument("--max-city-batches", type=int, default=0, help="0 = until done")
    parser.add_argument("--workers", type=int, default=0, help="City threads (0 = auto up to 12)")
    parser.add_argument("--hike-workers", type=int, default=0, help="Hike threads (0 = auto up to 6)")
    parser.add_argument("--photos", choices=["fast", "auto", "full"], default="fast")
    parser.add_argument("--tier", choices=["major", "regional", "town", "all"], default="all")
    parser.add_argument("--repair-first", action="store_true", help="Reset bad enriched rows")
    parser.add_argument("--sleep", type=float, default=4.0, help="Pause between batches (seconds)")
    args = parser.parse_args()
    configure_stdio()

    if args.repair_first:
        run([sys.executable, "scripts/repair-enriched-cards.py"])

    city_workers = resolve_workers(args.workers, cap=12)
    hike_workers = resolve_workers(args.hike_workers, cap=6)
    print(
        f"Orchestrator: {city_workers} city threads, {hike_workers} hike threads, "
        f"batch size {args.city_batch}, tier={args.tier}",
        flush=True,
    )

    batch_num = 0

    while True:
        batch_num += 1
        ct, ce, cp = count_pending(CITIES_DB, "cities")
        ht, he, hp = count_pending(HIKES_DB, "hikes")
        print(
            f"\n=== Batch {batch_num} | cities {ce}/{ct} enriched ({cp} pending) | "
            f"hikes {he}/{ht} enriched ({hp} pending) ===",
            flush=True,
        )

        if cp == 0 and hp == 0:
            print("Europe enrichment complete.", flush=True)
            break

        if args.max_city_batches and batch_num > args.max_city_batches:
            print("Reached --max-city-batches limit.", flush=True)
            break

        if hp > 0:
            hike_limit = str(args.hike_batch) if args.hike_batch > 0 else "0"
            hike_code = run(
                [
                    sys.executable,
                    "scripts/enrich-hikes-db.py",
                    "--workers",
                    str(hike_workers),
                    "--limit",
                    hike_limit,
                    "--progress",
                ]
            )
            if hike_code != 0:
                print("Hike batch failed; pausing before retry.", flush=True)
                time.sleep(30)

        if cp > 0:
            code = run(
                [
                    sys.executable,
                    "scripts/enrich-cities-db.py",
                    "--photos",
                    args.photos,
                    "--workers",
                    str(city_workers),
                    "--limit",
                    str(args.city_batch),
                    "--tier",
                    args.tier,
                    "--progress",
                ]
            )
            if code != 0:
                print("City batch failed; pausing before retry.", flush=True)
                time.sleep(45)

        time.sleep(max(0.0, args.sleep))


if __name__ == "__main__":
    main()
