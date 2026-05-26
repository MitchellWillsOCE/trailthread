#!/usr/bin/env python3
"""
For trails the Overpass-name-search couldn't resolve, query Wikidata SPARQL for the
trail name and look up its `P402 OSM Relation ID` property. This catches trails whose
OSM master relation has a different name (translation, branding, suffix) than the
seed but is correctly linked via Wikidata.

Outputs corrections directly to scripts/data/europe-hikes-seed.json (idempotent).

Usage:
  python scripts/resolve-hikes-via-wikidata.py --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "scripts" / "data" / "europe-hikes-seed.json"
PROGRESS_PATH = ROOT / "scripts" / "data" / "_seed-correction-progress.json"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

spec = importlib.util.spec_from_file_location(
    "build_hikes_db", ROOT / "scripts" / "build-hikes-db.py"
)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "Trailthread/1.0 (hike resolver via Wikidata)"


def safe(t: str) -> str:
    return str(t).encode("ascii", "replace").decode("ascii")


def sparql_lookup(name: str) -> list[dict]:
    """Find Wikidata items whose label/aliases match `name` and have P402 set."""
    name_escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    query = f"""
SELECT ?item ?itemLabel ?osm ?length WHERE {{
  {{
    ?item rdfs:label "{name_escaped}"@en .
  }}
  UNION
  {{
    ?item rdfs:label "{name_escaped}"@de .
  }}
  UNION
  {{
    ?item rdfs:label "{name_escaped}"@fr .
  }}
  UNION
  {{
    ?item rdfs:label "{name_escaped}"@es .
  }}
  UNION
  {{
    ?item rdfs:label "{name_escaped}"@it .
  }}
  UNION
  {{
    ?item skos:altLabel "{name_escaped}"@en .
  }}
  ?item wdt:P402 ?osm .
  OPTIONAL {{ ?item wdt:P2043 ?length . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
LIMIT 6
"""
    params = {"query": query, "format": "json"}
    url = WIKIDATA_SPARQL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  sparql FAIL: {e}")
        return []

    rows = []
    for binding in data.get("results", {}).get("bindings", []):
        osm_raw = binding.get("osm", {}).get("value", "")
        if not osm_raw or not osm_raw.isdigit():
            continue
        rows.append(
            {
                "wd_id": binding.get("item", {}).get("value", ""),
                "label": binding.get("itemLabel", {}).get("value", ""),
                "osm_id": int(osm_raw),
                "length_km": float(binding.get("length", {}).get("value", 0) or 0),
            }
        )
    return rows


def measure(osm_id: int) -> float:
    payload = build.fetch_relation(osm_id)
    if not payload:
        return 0.0
    return sum(build.line_length_km(c) for c in payload.get("chains", []) if len(c) >= 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="Only resolve these trail names")
    parser.add_argument("--apply", action="store_true", help="Write the corrected seed file")
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument(
        "--threshold-km",
        type=float,
        default=10.0,
        help="Trails whose current geometry is shorter than this are candidates for resolution",
    )
    args = parser.parse_args()

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    progress = {}
    if PROGRESS_PATH.exists():
        try:
            progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            progress = {}

    def cached_km(osm_id: int, name: str) -> float | None:
        for key, val in progress.items():
            if (
                val.get("picked_osm") == osm_id
                and key.endswith(f"::{name}")
            ):
                return float(val.get("picked_km", 0))
        return None

    corrections: list[tuple[dict, dict, float, float]] = []

    for seed in seeds:
        name = seed["name"]
        if args.only and name not in args.only:
            continue

        seed_osm = int(seed["osm_id"])
        seed_km = cached_km(seed_osm, name)
        if seed_km is None:
            try:
                seed_km = measure(seed_osm)
            except Exception:
                seed_km = 0.0
            time.sleep(args.sleep)

        if seed_km >= args.threshold_km and not args.only:
            continue  # already good enough

        print(f"[probe ] {safe(name):32s} cc={seed.get('cc',''):2s} seed_osm={seed_osm:>10d} seed_km={seed_km:.1f}")
        time.sleep(args.sleep)
        rows = sparql_lookup(name)
        time.sleep(args.sleep)
        if not rows:
            print("  no Wikidata match with P402")
            continue

        best_id = seed_osm
        best_km = seed_km
        for row in rows:
            cid = row["osm_id"]
            try:
                cand_km = measure(cid)
            except Exception:
                cand_km = 0.0
            time.sleep(args.sleep)
            print(
                f"  wd  {row['wd_id'].split('/')[-1]:>10s} osm={cid:>10d} km={cand_km:>7.1f} "
                f"label={safe(row['label'])[:40]}"
            )
            if cand_km > best_km + 1:
                best_id = cid
                best_km = cand_km

        if best_id != seed_osm and best_km > seed_km + 1:
            corrections.append((seed, {**seed, "osm_id": best_id}, seed_km, best_km))
            print(f"  -> CORRECT: {seed_osm} -> {best_id} ({seed_km:.0f} -> {best_km:.0f} km)")
        else:
            print(f"  -> no improvement")

    print()
    print(f"=== Wikidata resolver summary: {len(corrections)} corrections ===")
    for old_seed, new_seed, old_km, new_km in corrections:
        print(
            f"  {safe(old_seed['name']):32s} {old_seed['osm_id']:>10d} -> {new_seed['osm_id']:>10d}"
            f"  ({old_km:.0f} -> {new_km:.0f} km)"
        )

    if not args.apply or not corrections:
        if not args.apply:
            print("\n(dry run; pass --apply to write the seed file)")
        return

    correction_map = {seed["osm_id"]: new for seed, new, _, _ in corrections}
    new_seeds = [correction_map.get(s["osm_id"], s) for s in seeds]
    SEED_PATH.write_text(
        json.dumps(new_seeds, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote corrected seed file to {SEED_PATH}")


if __name__ == "__main__":
    main()
