#!/usr/bin/env python3
"""
Audit europe-hikes-seed.json and replace OSM relation IDs that point to fragments
with the actual *master* relation for each trail.

Strategy:
  1. For every seed entry, search Overpass for relations whose name matches the seed name
     in the seed country (or globally if no cc).
  2. For each viable candidate, fetch its full geometry recursively (sub-relations included)
     and measure the total length across all chains.
  3. Pick the candidate with the longest cumulative length, tie-broken by network rank
     (iwn > nwn > rwn > other) and presence of wikidata/wikipedia tags.
  4. If the picked candidate is materially better than the seed's current osm_id
     (length improvement >= 50% AND >= +10 km, OR seed currently produces < 5 km),
     update the seed.

The corrected file is written to scripts/data/europe-hikes-seed.json.
A `.bak` copy of the original is created if not already present.

Resume support: the script reads scripts/data/_seed-correction-progress.json and skips
trails it has already evaluated unless --force is passed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "scripts" / "data" / "europe-hikes-seed.json"
BACKUP_PATH = ROOT / "scripts" / "data" / "europe-hikes-seed.json.bak"
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


CC_TO_ISO = {
    "gb": "GB",
    "ie": "IE",
    "fr": "FR",
    "es": "ES",
    "pt": "PT",
    "it": "IT",
    "ch": "CH",
    "at": "AT",
    "de": "DE",
    "lu": "LU",
    "be": "BE",
    "nl": "NL",
    "no": "NO",
    "se": "SE",
    "fi": "FI",
    "is": "IS",
    "pl": "PL",
    "cz": "CZ",
    "sk": "SK",
    "hu": "HU",
    "si": "SI",
    "hr": "HR",
    "ba": "BA",
    "rs": "RS",
    "me": "ME",
    "mk": "MK",
    "al": "AL",
    "gr": "GR",
    "tr": "TR",
    "ro": "RO",
    "bg": "BG",
    "ua": "UA",
    "dk": "DK",
    "ee": "EE",
    "lv": "LV",
    "lt": "LT",
}


def safe(text: str) -> str:
    return str(text).encode("ascii", "replace").decode("ascii")


def network_rank(network: str) -> int:
    n = (network or "").lower()
    return {"iwn": 4, "nwn": 3, "rwn": 2, "lwn": 1}.get(n, 0)


def candidate_score(tags: dict) -> int:
    score = 0
    score += network_rank(tags.get("network", "")) * 50
    if tags.get("wikidata"):
        score += 30
    if tags.get("wikipedia"):
        score += 20
    if tags.get("ref"):
        score += 5
    return score


def _build_search_clause(area_clause: str, name: str) -> str:
    """Build a relations() search for hiking/foot routes by name and ref."""
    name_escaped = name.replace('"', '\\"').replace("\\", "\\\\")
    # Escape regex metacharacters in name for the case-insensitive name~ regex match
    import re as _re

    name_re = _re.escape(name).replace("/", "\\/")
    # Note: we intentionally don't restrict on type=route — some master hiking relations
    # have route=hiking with no explicit type tag, or use type=route_master, so the filter
    # would exclude them. The route=hiking|foot filter alone is enough.
    clauses = [
        f'relation["route"~"^(hiking|foot|walking)$"]["name"="{name_escaped}"]{area_clause};',
        f'relation["route"~"^(hiking|foot|walking)$"]["name:en"="{name_escaped}"]{area_clause};',
        f'relation["route"~"^(hiking|foot|walking)$"]["name"~"^{name_re}$",i]{area_clause};',
        # Fuzzy: name contains the seed name (handles "The X", "Le Y", "X Trail" etc.)
        f'relation["route"~"^(hiking|foot|walking)$"]["name"~"\\\\b{name_re}\\\\b",i]{area_clause};',
    ]
    ref_match = _re.match(r"^([A-Z]{1,4})\s*(\d{1,3}[A-Z]?)$", name.strip())
    if ref_match:
        prefix, num = ref_match.group(1), ref_match.group(2)
        ref_no_space = f"{prefix}{num}"
        ref_with_space = f"{prefix} {num}"
        for ref in {ref_no_space, ref_with_space}:
            clauses.append(
                f'relation["route"~"^(hiking|foot|walking)$"]["ref"="{ref}"]{area_clause};'
            )
    return "\n  ".join(clauses)


def _run_search(prelude: str, area_clause: str, name: str) -> list[dict]:
    inner = _build_search_clause(area_clause, name)
    q = f"""
[out:json][timeout:180];
{prelude}
(
  {inner}
);
out tags center;
"""
    try:
        data = build.http_post(q)
    except Exception as e:
        print(f"  search FAILED for {safe(name)}: {e}")
        return []
    rels = []
    seen_ids: set[int] = set()
    for el in data.get("elements", []):
        if el.get("type") != "relation":
            continue
        if el["id"] in seen_ids:
            continue
        seen_ids.add(el["id"])
        rels.append(el)
    return rels


def search_relations(name: str, cc: str) -> list[dict]:
    """Search Overpass for relations whose name (or ref) matches `name`.

    Always runs a global query (name conflicts across countries are rare for trails);
    additionally runs a country-scoped query and merges the two so the more selective
    area lookup also gets a chance to surface candidates Overpass might otherwise miss
    when a relation's geometry isn't fully inside the country's admin boundary."""
    iso = CC_TO_ISO.get((cc or "").lower())
    rels: list[dict] = _run_search("", "", name)
    if iso:
        more = _run_search(f'area["ISO3166-1"="{iso}"]->.a;', "(area.a)", name)
        seen = {int(r["id"]) for r in rels}
        for r in more:
            if int(r["id"]) not in seen:
                rels.append(r)
                seen.add(int(r["id"]))
    rels.sort(key=lambda r: candidate_score(r.get("tags", {})), reverse=True)
    return rels


def measure_relation_length(osm_id: int) -> tuple[float, int]:
    """Fetch the relation with deep recursion and return (total_km, chain_count)."""
    payload = build.fetch_relation(osm_id)
    if not payload:
        return 0.0, 0
    chains = payload.get("chains", [])
    total = sum(build.line_length_km(c) for c in chains if len(c) >= 2)
    return total, len(chains)


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-evaluate trails already in progress file")
    parser.add_argument("--only", nargs="*", help="Only correct these trail names")
    parser.add_argument("--max-candidates", type=int, default=3, help="Top N candidates to length-test per trail")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds between Overpass calls")
    parser.add_argument("--apply", action="store_true", help="Write corrected seed file (otherwise dry-run)")
    args = parser.parse_args()

    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if not BACKUP_PATH.exists():
        BACKUP_PATH.write_text(json.dumps(seeds, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Backed up original seed to {BACKUP_PATH}")

    progress = load_progress()
    only = set(args.only or [])

    corrections: list[tuple[dict, dict, float, float]] = []
    keeps: list[tuple[dict, float]] = []

    for seed in seeds:
        name = seed["name"]
        cc = seed.get("cc", "")
        seed_osm = int(seed["osm_id"])
        if only and name not in only:
            continue

        progress_key = f"{seed_osm}::{name}"
        if not args.force and progress_key in progress:
            cached = progress[progress_key]
            print(
                f"[cached] {safe(name):32s} osm={seed_osm:>10d} -> {cached['picked_osm']:>10d} "
                f"({cached['picked_km']:.0f} km vs seed {cached['seed_km']:.0f} km)"
            )
            if cached["picked_osm"] != seed_osm:
                replacement = {**seed, "osm_id": cached["picked_osm"]}
                corrections.append((seed, replacement, cached["seed_km"], cached["picked_km"]))
            continue

        print(f"[probe ] {safe(name):32s} cc={cc} seed_osm={seed_osm}")
        try:
            seed_km, _ = measure_relation_length(seed_osm)
        except Exception as e:
            print(f"  seed measure FAIL: {e}")
            seed_km = 0.0
        time.sleep(args.sleep)

        candidates = search_relations(name, cc)[: args.max_candidates]
        time.sleep(args.sleep)
        if not candidates:
            print(f"  no candidates found, keeping seed (km={seed_km:.1f})")
            progress[progress_key] = {
                "seed_km": seed_km,
                "picked_osm": seed_osm,
                "picked_km": seed_km,
                "candidate_ids": [],
            }
            save_progress(progress)
            keeps.append((seed, seed_km))
            continue

        best_id = seed_osm
        best_km = seed_km
        candidate_results = []
        for cand in candidates:
            cid = int(cand["id"])
            if cid == seed_osm:
                cand_km = seed_km
            else:
                try:
                    cand_km, _ = measure_relation_length(cid)
                except Exception as e:
                    print(f"  cand {cid} measure FAIL: {e}")
                    cand_km = 0.0
                time.sleep(args.sleep)
            cand_score = candidate_score(cand.get("tags", {}))
            cname = cand.get("tags", {}).get("name", "")
            print(f"  cand {cid:>10d} score={cand_score:>3d} km={cand_km:>7.1f} {safe(cname)[:40]}")
            candidate_results.append({"id": cid, "km": cand_km, "score": cand_score, "name": cname})
            # Pick longest, tie-break by score
            if cand_km > best_km + 0.5 or (
                cand_km > best_km * 0.85 and cand_score > candidate_score(
                    next((c for c in candidates if int(c["id"]) == best_id), {}).get("tags", {})
                )
            ):
                best_id = cid
                best_km = cand_km

        progress[progress_key] = {
            "seed_km": seed_km,
            "picked_osm": best_id,
            "picked_km": best_km,
            "candidates": candidate_results,
        }
        save_progress(progress)

        improved = (
            best_id != seed_osm
            and best_km > 0
            and (best_km >= max(seed_km * 1.5, seed_km + 10) or seed_km < 5)
        )
        if improved:
            replacement = {**seed, "osm_id": best_id}
            corrections.append((seed, replacement, seed_km, best_km))
            print(f"  -> CORRECT: {seed_osm} -> {best_id}  ({seed_km:.0f} -> {best_km:.0f} km)")
        else:
            keeps.append((seed, seed_km))
            print(f"  -> KEEP  : {seed_osm}  ({seed_km:.0f} km)")

    print()
    print("=== Summary ===")
    print(f"Trails kept:        {len(keeps)}")
    print(f"Trails to correct:  {len(corrections)}")
    for old_seed, new_seed, old_km, new_km in corrections:
        print(
            f"  {safe(old_seed['name']):32s} {old_seed['osm_id']:>10d} -> {new_seed['osm_id']:>10d}"
            f"  ({old_km:.0f} -> {new_km:.0f} km)"
        )

    if not args.apply:
        print("\n(dry run; pass --apply to write the seed file)")
        return

    if not corrections:
        print("\nNo corrections to apply.")
        return

    correction_map = {seed["osm_id"]: new for seed, new, _, _ in corrections}
    new_seeds = []
    for entry in seeds:
        new_seeds.append(correction_map.get(entry["osm_id"], entry))

    SEED_PATH.write_text(
        json.dumps(new_seeds, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote corrected seed file to {SEED_PATH}")


if __name__ == "__main__":
    main()
