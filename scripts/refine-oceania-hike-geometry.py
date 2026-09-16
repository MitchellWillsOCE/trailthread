#!/usr/bin/env python3
"""Replace sparse Oceania hike sketches with OpenStreetMap hiking geometries.

Existing Australia/NZ catalog paths are typically 2–5 coarse waypoints. The map
used to split those long gaps and snap each piece independently, which left
start and finish markers off the visible line. This worker pulls named OSM
hiking relations and ways, stitches them into a continuous path, and writes
the denser LineString back into oceania-seed.json.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "scripts" / "data" / "oceania-seed.json"
CACHE_PATH = ROOT / "scripts" / "data" / "oceania-hike-geometry-cache.json"
SEED_OCEANIA = ROOT / "scripts" / "seed-oceania.py"

spec = importlib.util.spec_from_file_location("build_hikes_db", ROOT / "scripts" / "build-hikes-db.py")
build = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build)


def overpass_post(query: str, *, retries: int = 2, timeout: int = 45) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err: Exception | None = None
    endpoints = build.OVERPASS_ENDPOINTS
    for attempt in range(retries):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"User-Agent": build.USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
            time.sleep(min(20, 2 + 3 * attempt))
    raise RuntimeError(f"Overpass failed: {last_err}")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_err = None
    for attempt in range(6):
        try:
            tmp.replace(path)
            return
        except OSError as err:
            last_err = err
            time.sleep(0.4 * (attempt + 1))
    path.write_text(text, encoding="utf-8")
    tmp.unlink(missing_ok=True)
    if last_err:
        print(f"warn: replaced seed via direct write after {last_err}", flush=True)


def flatten_coords(raw) -> list[list[float]]:
    if isinstance(raw, dict):
        if raw.get("type") == "LineString":
            return [list(pt) for pt in raw.get("coordinates") or [] if len(pt) >= 2]
        if raw.get("type") == "MultiLineString":
            points = []
            for chain in raw.get("coordinates") or []:
                points.extend(list(pt) for pt in chain if len(pt) >= 2)
            return points
        return []
    return [list(pt) for pt in (raw or []) if isinstance(pt, (list, tuple)) and len(pt) >= 2]


def haversine_km(a: list[float], b: list[float]) -> float:
    return build.haversine_km((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))


def line_length_km(coords: list[list[float]]) -> float:
    return build.line_length_km(coords)


def widest_gap_km(coords: list[list[float]]) -> float:
    widest = 0.0
    for i in range(1, len(coords)):
        widest = max(widest, haversine_km(coords[i - 1], coords[i]))
    return widest


def is_loop(hike: dict, coords: list[list[float]]) -> bool:
    start = (hike.get("start_name") or "").strip().lower()
    end = (hike.get("end_name") or "").strip().lower()
    if start and end and start == end:
        return True
    if len(coords) >= 2 and haversine_km(coords[0], coords[-1]) < 0.25:
        return True
    name = (hike.get("name") or "").lower()
    return any(token in name for token in ("circuit", "loop", "rim walk"))


def close_loop(coords: list[list[float]]) -> list[list[float]]:
    if len(coords) < 3:
        return coords
    if haversine_km(coords[0], coords[-1]) > 0.02:
        return coords + [list(coords[0])]
    coords[-1] = list(coords[0])
    return coords


def densify(coords: list[list[float]], spacing_km: float = 0.25, max_points: int = 240) -> list[list[float]]:
    if len(coords) < 2:
        return coords
    total = max(line_length_km(coords), 0.01)
    if total <= 12:
        spacing_km = min(spacing_km, 0.12)
    spacing_km = max(spacing_km, total / max(max_points - 1, 1))
    out = [list(coords[0])]
    for a, b in zip(coords, coords[1:]):
        gap = max(haversine_km(a, b), 1e-9)
        steps = max(1, int(math.ceil(gap / spacing_km)))
        for i in range(1, steps + 1):
            t = i / steps
            out.append([
                round(a[0] + (b[0] - a[0]) * t, 6),
                round(a[1] + (b[1] - a[1]) * t, 6),
            ])
    return out[: max_points + 8]


def hike_anchor(hike: dict) -> tuple[float, float]:
    coords = flatten_coords(hike.get("geometry"))
    if coords:
        mid = coords[len(coords) // 2]
        return float(mid[1]), float(mid[0])
    return 0.0, 0.0


def hike_radius_km(hike: dict) -> float:
    length = float(hike.get("length_km") or 8)
    coords = flatten_coords(hike.get("geometry"))
    span = 0.0
    if len(coords) >= 2:
        lngs = [pt[0] for pt in coords]
        lats = [pt[1] for pt in coords]
        span = haversine_km([min(lngs), min(lats)], [max(lngs), max(lats)])
    return max(8.0, min(90.0, max(length * 0.7, span * 0.7) + 6.0))


def bbox_around(lat: float, lng: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.3, math.cos(math.radians(lat))))
    south, north = lat - dlat, lat + dlat
    west, east = lng - dlng, lng + dlng
    return f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})"


KNOWN_ALIASES = {
    "overland-track-au": ["Overland Track"],
    "larapinta-trail-au": ["Larapinta Trail"],
    "cape-to-cape-track-au": ["Cape to Cape Track", "Cape to Cape"],
    "great-ocean-walk-au": ["Great Ocean Walk"],
    "six-foot-track-au": ["Six Foot Track"],
    "three-capes-track-au": ["Three Capes Track"],
    "bibbulmun-track-au": ["Bibbulmun Track"],
    "heysen-trail-au": ["Heysen Trail"],
    "australian-alps-walking-track-au": ["Australian Alps Walking Track"],
    "jatbula-trail-au": ["Jatbula Trail"],
    "thorsborne-trail-au": ["Thorsborne Trail"],
    "kosciuszko-main-range-walk-au": ["Main Range Track", "Main Range Walk"],
    "mount-kosciuszko-summit-walk-au": ["Mount Kosciuszko Summit Trail", "Summit Walk"],
    "bondi-to-coogee-walk-au": ["Bondi to Coogee", "Bondi to Coogee Walk"],
    "royal-national-park-coast-track-au": ["Coast Track", "Royal Coast Track"],
    "dove-lake-circuit-au": ["Dove Lake Circuit"],
    "kings-canyon-rim-walk-au": ["Kings Canyon Rim Walk", "Rim Walk"],
    "routeburn-track-nz": ["Routeburn Track"],
    "milford-track-nz": ["Milford Track"],
    "tongariro-alpine-crossing-nz": ["Tongariro Alpine Crossing"],
    "abel-tasman-coast-track-nz": ["Abel Tasman Coast Track"],
    "kepler-track-nz": ["Kepler Track"],
    "hooker-valley-track-nz": ["Hooker Valley Track"],
    "wineglass-bay-lookout-track-au": ["Wineglass Bay Lookout"],
    "cape-hauy-track-au": ["Cape Hauy"],
    "bluff-knoll-walk-au": ["Bluff Knoll"],
    "mount-warning-wollumbin-au": ["Wollumbin", "Mount Warning"],
    "pinnacle-walk-grampians-au": ["The Pinnacle", "Pinnacle Walk"],
}


def aliases_for(hike: dict) -> list[str]:
    names = []
    names.extend(KNOWN_ALIASES.get(hike.get("id"), []))
    for value in [hike.get("name"), *(hike.get("osm_aliases") or [])]:
        text = (value or "").strip()
        if text:
            names.append(text)
    extra = []
    for name in list(names):
        trimmed = re.sub(
            r"\b(walk|track|trail|circuit|loop|summit|hike|via|the)\b",
            " ",
            name,
            flags=re.I,
        )
        trimmed = re.sub(r"\s+", " ", trimmed).strip(" -/")
        if trimmed and trimmed.lower() not in {n.lower() for n in names}:
            extra.append(trimmed)
    names.extend(extra)
    seen = set()
    out = []
    for name in names:
        key = name.lower()
        if key in seen or len(name) < 4:
            continue
        seen.add(key)
        out.append(name)
    return out[:3]


def score_name(candidate: str, aliases: list[str]) -> int:
    cand = (candidate or "").lower()
    if not cand:
        return 0
    best = 0
    for alias in aliases:
        alias_l = alias.lower()
        if cand == alias_l:
            best = max(best, 100)
        elif alias_l in cand or cand in alias_l:
            best = max(best, 80)
        elif any(part and part in cand for part in re.split(r"\s+", alias_l) if len(part) > 4):
            best = max(best, 40)
    return best


def hike_bbox(hike: dict) -> str:
    coords = flatten_coords(hike.get("geometry"))
    if len(coords) >= 2:
        lngs = [float(pt[0]) for pt in coords]
        lats = [float(pt[1]) for pt in coords]
        pad_lat = 0.07
        pad_lng = 0.08
        return f"({min(lats) - pad_lat:.5f},{min(lngs) - pad_lng:.5f},{max(lats) + pad_lat:.5f},{max(lngs) + pad_lng:.5f})"
    lat, lng = hike_anchor(hike)
    return bbox_around(lat, lng, min(14.0, hike_radius_km(hike)))


def search_osm(name: str, hike: dict) -> dict:
    name_re = re.escape(name).replace("/", "\\/")
    bbox = hike_bbox(hike)
    query = f"""
    [out:json][timeout:40];
    (
      relation["route"~"^(hiking|foot|walking)$"]["name"~"{name_re}",i]{bbox};
      relation["route"~"^(hiking|foot|walking)$"]["ref"~"{name_re}",i]{bbox};
      way["highway"~"path|footway|steps|track"]["name"~"{name_re}",i]{bbox};
      way["sac_scale"]["name"~"{name_re}",i]{bbox};
    );
    out tags geom;
    """
    return overpass_post(query)


def ways_from_elements(elements: list[dict]) -> list[list[list[float]]]:
    segments = []
    for el in elements:
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        pts = [[pt["lon"], pt["lat"]] for pt in el["geometry"] if "lat" in pt and "lon" in pt]
        if len(pts) >= 2:
            segments.append(pts)
    return segments


def pick_relation(elements: list[dict], aliases: list[str]) -> dict | None:
    rels = [el for el in elements if el.get("type") == "relation"]
    if not rels:
        return None
    rels.sort(key=lambda el: score_name((el.get("tags") or {}).get("name", ""), aliases), reverse=True)
    best = rels[0]
    if score_name((best.get("tags") or {}).get("name", ""), aliases) < 40:
        return None
    return best


def geometry_from_chains(chains: list[list[list[float]]], loop: bool) -> list[list[float]] | None:
    if not chains:
        return None
    longest = max(chains, key=line_length_km)
    if loop:
        longest = close_loop(longest)
    return build.simplify_coords(longest, max_points=900)


def accept_length(osm_km: float, expected_km: float) -> bool:
    if osm_km < 0.35:
        return False
    if expected_km <= 8:
        return osm_km <= max(22.0, expected_km * 5)
    return expected_km * 0.22 <= osm_km <= expected_km * 2.8


def fetch_hike_geometry(hike: dict) -> tuple[list[list[float]] | None, str, int | None]:
    aliases = aliases_for(hike)
    expected = float(hike.get("length_km") or 0)
    loop = is_loop(hike, flatten_coords(hike.get("geometry")))
    best_coords = None
    best_note = "no-match"
    best_osm = None
    best_score = -1.0

    for alias in aliases:
        try:
            data = search_osm(alias, hike)
        except Exception as err:
            best_note = f"search-error:{err}"
            break
        elements = data.get("elements") or []
        segments = ways_from_elements(elements)
        if segments:
            chains = build.stitch_into_chains(segments, max_join_km=0.35)
            coords = geometry_from_chains(chains, loop)
            if coords:
                length = line_length_km(coords)
                if accept_length(length, expected or length) and length > best_score:
                    best_coords = coords
                    best_note = f"ways:{alias}:{length:.1f}km/{len(coords)}pts"
                    best_score = length
                    coverage = (length / expected) if expected else 1.0
                    if coverage >= 0.55 or (expected <= 12 and length >= 0.6):
                        return best_coords, best_note, best_osm
        rel = pick_relation(elements, aliases)
        if rel:
            best_osm = int(rel["id"])
            # Full relation downloads are only worth it for short walks; long
            # trails already arrive as named ways in the search payload.
            if expected and expected <= 18 and (not best_coords or best_score < expected * 0.55):
                payload = build.fetch_relation(int(rel["id"]))
                if payload and payload.get("coordinates"):
                    coords = geometry_from_chains(payload.get("chains") or [payload["coordinates"]], loop)
                    if coords:
                        length = line_length_km(coords)
                        if accept_length(length, expected or length) and length > best_score:
                            best_coords = coords
                            best_note = f"relation:{rel['id']}:{length:.1f}km"
                            best_score = length
                            return best_coords, best_note, best_osm
        time.sleep(0.35)
    return best_coords, best_note, best_osm


def fallback_geometry(hike: dict) -> list[list[float]]:
    coords = flatten_coords(hike.get("geometry"))
    if len(coords) < 2:
        return coords
    dense = densify(coords, spacing_km=0.22)
    if is_loop(hike, coords):
        dense = close_loop(dense)
    return dense


def needs_refine(hike: dict, force: bool) -> bool:
    if force:
        return True
    coords = flatten_coords(hike.get("geometry"))
    if len(coords) < 12:
        return True
    return widest_gap_km(coords) > 2.4


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace sparse Oceania hike sketches with OSM paths.")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if geometry already looks dense")
    parser.add_argument("--only", nargs="*", help="Only refine these hike ids")
    parser.add_argument("--limit", type=int, default=0, help="Max hikes to process this run")
    parser.add_argument("--no-apply", action="store_true", help="Update seed JSON only")
    parser.add_argument("--densify-only", action="store_true", help="Close gaps without calling Overpass")
    parser.add_argument("--sleep", type=float, default=0.6, help="Pause between hikes")
    args = parser.parse_args()

    seed = read_json(SEED_PATH)
    cache = read_json(CACHE_PATH, {}) or {}
    only = set(args.only or [])
    processed = 0
    updated = 0
    fetched = 0
    fallback = 0

    for hike in seed.get("hikes", []):
        hike_id = hike.get("id") or hike.get("name")
        if only and hike_id not in only:
            continue
        if not needs_refine(hike, args.force):
            continue
        if args.limit and processed >= args.limit:
            break
        processed += 1
        print(f"[{processed}] {hike_id}: {hike.get('name')}", flush=True)
        if args.densify_only:
            coords, note, osm_id = None, "densify-only", hike.get("osm_id")
        else:
            coords, note, osm_id = fetch_hike_geometry(hike)
        source = "osm"
        if not coords:
            coords = fallback_geometry(hike)
            source = "densify"
            fallback += 1
            print(f"  fallback densify ({note}) -> {len(coords)} pts", flush=True)
        else:
            fetched += 1
            print(f"  {note} -> {len(coords)} pts", flush=True)
        hike["geometry"] = coords
        if osm_id:
            hike["osm_id"] = osm_id
        cache[hike_id] = {
            "source": source,
            "note": note,
            "points": len(coords),
            "km": round(line_length_km(coords), 2),
            "osm_id": osm_id,
        }
        updated += 1
        time.sleep(args.sleep)

    write_json(SEED_PATH, seed)
    write_json(CACHE_PATH, cache)
    print(f"updated={updated} osm={fetched} densify={fallback}", flush=True)

    if not args.no_apply:
        import subprocess
        import sys

        subprocess.run([sys.executable, str(SEED_OCEANIA)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
