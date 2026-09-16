#!/usr/bin/env python3
"""
Build European hiking trail catalog from OpenStreetMap (Overpass API).

Data source: OSM relations tagged route=hiking and major walking networks (iwn/nwn/rwn).
Popularity is scored from seed weights, network type, length, and OSM metadata.

Usage:
  python scripts/build-hikes-db.py
  python scripts/build-hikes-db.py --discover --limit 800
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
SCHEMA_PATH = ROOT / "scripts" / "schema" / "hikes.sql"
SEED_PATH = ROOT / "scripts" / "data" / "europe-hikes-seed.json"
MONTENEGRO_SEED_PATH = ROOT / "scripts" / "data" / "montenegro-hikes-seed.json"
CROATIA_SEED_PATH = ROOT / "scripts" / "data" / "croatia-adriatic-hikes-seed.json"
OCEANIA_SEED_PATH = ROOT / "scripts" / "data" / "oceania-seed.json"
DISCOVERED_CACHE_PATH = ROOT / "scripts" / "data" / "europe-hikes-discovered-cache.json"

CC_TO_COUNTRY = {
    "at": "Austria",
    "be": "Belgium",
    "bg": "Bulgaria",
    "ch": "Switzerland",
    "cz": "Czechia",
    "de": "Germany",
    "dk": "Denmark",
    "ee": "Estonia",
    "es": "Spain",
    "fi": "Finland",
    "fr": "France",
    "gb": "United Kingdom",
    "gr": "Greece",
    "hr": "Croatia",
    "hu": "Hungary",
    "ie": "Ireland",
    "is": "Iceland",
    "it": "Italy",
    "lt": "Lithuania",
    "lu": "Luxembourg",
    "lv": "Latvia",
    "me": "Montenegro",
    "nl": "Netherlands",
    "no": "Norway",
    "pl": "Poland",
    "pt": "Portugal",
    "ro": "Romania",
    "rs": "Serbia",
    "se": "Sweden",
    "si": "Slovenia",
    "sk": "Slovakia",
    "tr": "Turkey",
    "ua": "Ukraine",
}
DB_PATH = ROOT / "Trip" / "hikes" / "hikes.db"
MANIFEST_PATH = ROOT / "Trip" / "hikes" / "manifest.json"
REGION_LABELS = {
    "europe": "Europe",
    "oceania": "Oceania",
}
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
USER_AGENT = "Trailthread/1.0 (hiking catalog build)"
EUROPE_BBOX = (35.0, -25.0, 72.0, 45.0)  # south, west, north, east
NOTABLE_NETWORKS = frozenset({"iwn", "nwn", "rwn"})
SEGMENT_NAME_RE = re.compile(
    r"^(\d{1,3}\s*[-–]\s*\d{1,3}|\d{3}[A-Z]?\s+.+|AW\d+|etappe\s+\d+|stage\s+\d+)$",
    re.I,
)
LOCAL_CONNECTOR_RE = re.compile(r"^.+\s+[-–]\s+.+$", re.I)


def http_post(query: str, *, retries: int = 8) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_err: Exception | None = None
    n_eps = len(OVERPASS_ENDPOINTS)
    for attempt in range(retries):
        endpoint = OVERPASS_ENDPOINTS[attempt % n_eps]
        try:
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            last_err = err
            if err.code in (408, 429, 502, 503, 504) and attempt < retries - 1:
                time.sleep(min(90, 5 + 4 * attempt))
                continue
            if attempt < retries - 1:
                time.sleep(min(60, 3 * (attempt + 1)))
                continue
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            last_err = err
            if attempt < retries - 1:
                time.sleep(min(60, 3 * (attempt + 1)))
                continue
    raise RuntimeError(f"Overpass failed: {last_err}")


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[1]), math.radians(a[0])
    lat2, lng2 = math.radians(b[1]), math.radians(b[0])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def line_length_km(coords: list[list[float]]) -> float:
    total = 0.0
    for i in range(1, len(coords)):
        total += haversine_km(coords[i - 1], coords[i])
    return total


def simplify_coords(coords: list[list[float]], max_points: int = 600) -> list[list[float]]:
    if len(coords) <= max_points:
        return coords
    step = max(1, (len(coords) - 1) // (max_points - 1))
    simplified = [coords[0]]
    for i in range(step, len(coords) - 1, step):
        simplified.append(coords[i])
    if simplified[-1] != coords[-1]:
        simplified.append(coords[-1])
    return simplified


def simplify_chains(
    chains: list[list[list[float]]], total_budget: int = 4000
) -> list[list[list[float]]]:
    """Simplify each chain proportionally to its length so long-distance trails keep detail."""
    if not chains:
        return []
    chain_lens = [max(line_length_km(c), 0.001) for c in chains]
    total_len = sum(chain_lens)
    out: list[list[list[float]]] = []
    for chain, length in zip(chains, chain_lens):
        share = max(40, int(round(total_budget * length / total_len)))
        out.append(simplify_coords(chain, max_points=min(share, len(chain))))
    return [c for c in out if len(c) >= 2]


def bbox_from_chains(chains: list[list[list[float]]]) -> tuple[float, float, float, float]:
    lngs = [pt[0] for chain in chains for pt in chain]
    lats = [pt[1] for chain in chains for pt in chain]
    return min(lngs), min(lats), max(lngs), max(lats)


def centroid_of_chains(chains: list[list[list[float]]]) -> tuple[float, float]:
    pts = [pt for chain in chains for pt in chain]
    if not pts:
        return 0.0, 0.0
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lng, lat


def total_length_km(chains: list[list[list[float]]]) -> float:
    return sum(line_length_km(c) for c in chains if len(c) >= 2)


def _near_km(a: tuple[float, float], b: tuple[float, float], max_km: float = 0.25) -> bool:
    return haversine_km(a, b) <= max_km


def stitch_into_chains(
    segments: list[list[list[float]]], max_join_km: float = 0.25
) -> list[list[list[float]]]:
    """Join segments end-to-end where their endpoints are within max_join_km. Returns ALL chains.

    Never collapses to a single chain: if a route has gaps wider than `max_join_km`
    (common for long-distance trails crossing rivers, ferries, missing OSM ways) the
    disconnected pieces are returned as separate chains so the geometry stays accurate.
    """
    segments = [list(s) for s in segments if len(s) >= 2]
    if not segments:
        return []

    def orient(seg: list[list[float]], reverse: bool) -> list[list[float]]:
        return list(reversed(seg)) if reverse else list(seg)

    def attach(chain: list[list[float]], seg: list[list[float]]) -> tuple[list[list[float]], float] | None:
        end, start = chain[-1], chain[0]
        options: list[tuple[float, str, bool]] = [
            (haversine_km(end, seg[0]), "append", False),
            (haversine_km(end, seg[-1]), "append", True),
            (haversine_km(start, seg[-1]), "prepend", False),
            (haversine_km(start, seg[0]), "prepend", True),
        ]
        options = [(d, mode, rev) for d, mode, rev in options if d <= max_join_km]
        if not options:
            return None
        dist, mode, rev = min(options, key=lambda item: item[0])
        oriented = orient(seg, rev)
        if mode == "append":
            merged = chain + (oriented[1:] if _near_km(end, oriented[0], max_join_km) else oriented)
        else:
            merged = (oriented[:-1] if _near_km(start, oriented[-1], max_join_km) else oriented) + chain
        return merged, dist

    unused = sorted(segments, key=len, reverse=True)
    chains: list[list[list[float]]] = []

    while unused:
        chain = list(unused.pop(0))
        improved = True
        while improved:
            improved = False
            best_idx = -1
            best_chain: list[list[float]] | None = None
            best_dist = float("inf")
            for i, seg in enumerate(unused):
                attached = attach(chain, seg)
                if not attached:
                    continue
                merged, dist = attached
                if dist < best_dist:
                    best_idx = i
                    best_chain = merged
                    best_dist = dist
            if best_idx >= 0 and best_chain is not None:
                chain = best_chain
                unused.pop(best_idx)
                improved = True
        chains.append(chain)

    return chains


def collect_chains_from_response(elements: list[dict], root_relation_id: int) -> list[list[list[float]]]:
    """Walk an Overpass response with deep recursion, descending into sub-relations.

    Returns a list of chains (each chain is a list of [lng, lat] points). Long-distance
    trails on OSM are typically a super-relation containing one sub-relation per stage
    — without recursion only the directly attached ways are seen, which is why some
    routes previously rendered as a tiny fragment.
    """
    way_coords: dict[int, list[list[float]]] = {}
    relations: dict[int, dict] = {}
    nodes: dict[int, tuple[float, float]] = {}

    for el in elements:
        et = el.get("type")
        if et == "way":
            if el.get("geometry"):
                pts = [[pt["lon"], pt["lat"]] for pt in el["geometry"] if "lat" in pt and "lon" in pt]
                if len(pts) >= 2:
                    way_coords[el["id"]] = pts
            elif el.get("nodes"):
                way_coords.setdefault(el["id"], [])
                way_coords[el["id"]] = el["nodes"]
        elif et == "relation":
            relations[el["id"]] = el
        elif et == "node" and "lat" in el and "lon" in el:
            nodes[el["id"]] = (el["lon"], el["lat"])

    for way_id, payload in list(way_coords.items()):
        if payload and isinstance(payload[0], int):
            built = [list(nodes[nid]) for nid in payload if nid in nodes]
            way_coords[way_id] = built if len(built) >= 2 else []

    root = relations.get(root_relation_id)
    if not root:
        return []

    visited: set[int] = set()
    segments: list[list[list[float]]] = []

    def walk(rel: dict) -> None:
        if rel["id"] in visited:
            return
        visited.add(rel["id"])
        for member in rel.get("members", []):
            mtype = member.get("type")
            if mtype == "way":
                coords = way_coords.get(member.get("ref"))
                if not coords or len(coords) < 2:
                    continue
                if member.get("role") == "backward":
                    coords = list(reversed(coords))
                segments.append(list(coords))
            elif mtype == "relation":
                child = relations.get(member.get("ref"))
                if child:
                    walk(child)

    walk(root)
    return stitch_into_chains(segments)


def stitch_segments(segments: list[list[list[float]]], max_join_km: float = 0.25) -> list[list[float]]:
    """Backward-compat: return the longest chain after stitching (used by ferry build)."""
    chains = stitch_into_chains(segments, max_join_km=max_join_km)
    if not chains:
        return []
    return max(chains, key=line_length_km)


def _near(a: tuple[float, float], b: tuple[float, float], eps: float = 1e-5) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def fetch_relation(osm_id: int) -> dict | None:
    """Fetch a relation with deep recursion so sub-relation ways come back too."""
    query_geom = f"""
    [out:json][timeout:240];
    relation({osm_id});
    (._;>>;);
    out geom;
    """
    query_body = f"""
    [out:json][timeout:240];
    relation({osm_id});
    (._;>>;);
    out body;
    >;
    out skel qt;
    """
    data = None
    chains: list[list[list[float]]] = []
    for query in (query_geom, query_body):
        try:
            data = http_post(query)
        except Exception as err:
            print(f"  skip relation {osm_id}: {err}")
            return None
        chains = collect_chains_from_response(data.get("elements", []), osm_id)
        if chains:
            break

    if not chains:
        return None

    rel = next(
        (e for e in data.get("elements", []) if e.get("type") == "relation" and e.get("id") == osm_id),
        None,
    )
    tags = rel.get("tags", {}) if rel else {}
    longest_chain = max(chains, key=line_length_km)
    return {
        "osm_id": osm_id,
        "tags": tags,
        "chains": chains,
        "coordinates": longest_chain,
    }


MONTENEGRO_BBOX = (41.75, 18.43, 43.65, 20.39)  # south, west, north, east


def normalize_trail_name(name: str) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def is_segment_or_stub_name(name: str) -> bool:
    text = (name or "").strip()
    if len(text) < 5:
        return True
    if SEGMENT_NAME_RE.match(text):
        return True
    if re.fullmatch(r"[\d\s\-–]+", text):
        return True
    if re.match(r"^\d{3}[A-Z]?\s", text):
        return True
    return False


def tags_indicate_notable(tags: dict) -> bool:
    network = (tags.get("network") or "").lower()
    if network in NOTABLE_NETWORKS:
        return True
    if tags.get("wikidata") or tags.get("wikipedia"):
        return True
    ref = (tags.get("ref") or "").upper()
    if re.match(r"^(E\d{1,2}|GR\s*\d+)", ref):
        return True
    name = tags.get("name") or ""
    if len(name) >= 14 and re.search(
        r"\b(way|weg|trail|route|camino|via|coast path|haute route|alta via|leden|steig|sentiero|wanderweg)\b",
        name,
        re.I,
    ):
        return True
    return False


def should_keep_discovered(tags: dict, record: dict, *, min_length_km: float) -> bool:
    if not tags_indicate_notable(tags):
        return False
    if is_segment_or_stub_name(record["name"]):
        return False
    notable_meta = bool(tags.get("wikidata") or tags.get("wikipedia"))
    if record["length_km"] < min_length_km and not notable_meta:
        return False
    if LOCAL_CONNECTOR_RE.match(record["name"]) and record["length_km"] < 60 and not notable_meta:
        return False
    return True


def dedupe_hikes(hikes: list[dict]) -> list[dict]:
    """Drop duplicate names and near-duplicate place-to-place connectors."""
    groups: dict[str, list[dict]] = {}
    for hike in hikes:
        key = normalize_trail_name(hike["name"])
        if not key:
            key = hike["id"]
        groups.setdefault(key, []).append(hike)

    kept: list[dict] = []
    for group in groups.values():
        best = max(group, key=lambda h: (h["popularity"], h["length_km"]))
        kept.append(best)

    return kept


def discover_relations(limit: int, *, bbox: tuple[float, float, float, float] | None = None) -> list[dict]:
    south, west, north, east = bbox or EUROPE_BBOX
    if bbox == MONTENEGRO_BBOX:
        query = f"""
        [out:json][timeout:300];
        area["ISO3166-1"="ME"][admin_level=2]->.me;
        (
          relation["route"="hiking"](area.me);
          relation["route"="foot"]["network"~"iwn|nwn|rwn|lwn"](area.me);
        );
        out tags center;
        """
    else:
        query = f"""
        [out:json][timeout:300];
        (
          relation["route"="hiking"]["network"~"iwn|nwn|rwn"]({south},{west},{north},{east});
          relation["route"="hiking"]["wikidata"]({south},{west},{north},{east});
          relation["route"="hiking"]["wikipedia"]({south},{west},{north},{east});
        );
        out tags center;
        """
    print(f"Discovering up to {limit} notable hiking relations from OSM…")
    data = http_post(query)
    results = []
    for el in data.get("elements", []):
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("ref")
        if not name or is_segment_or_stub_name(name):
            continue
        if not tags_indicate_notable(tags):
            continue
        center = el.get("center") or {}
        results.append(
            {
                "osm_id": el["id"],
                "name": name,
                "tags": tags,
                "center_lat": center.get("lat"),
                "center_lon": center.get("lon"),
            }
        )
    results.sort(key=lambda r: score_tags(r.get("tags", {}), 50), reverse=True)
    return results[:limit]


def score_tags(tags: dict, seed_popularity: int = 50) -> int:
    score = seed_popularity
    network = (tags.get("network") or "").lower()
    if network in ("iwn", "nwn", "rwn"):
        score += 18
    if tags.get("wikidata"):
        score += 22
    if tags.get("wikipedia"):
        score += 14
    if tags.get("ref"):
        score += 8
    if tags.get("name"):
        score += 5
    route = tags.get("route", "")
    if route == "hiking":
        score += 6
    return min(100, score)


def tier_from_popularity(pop: int) -> str:
    if pop >= 75:
        return "major"
    if pop >= 50:
        return "regional"
    return "local"


def difficulty_from_tags(tags: dict) -> str:
    sac = tags.get("sac_scale") or tags.get("hiking:difficulty")
    if sac:
        return sac
    return tags.get("difficulty") or "moderate"


def country_from_tags(tags: dict, *, fallback_country: str = "Europe", fallback_cc: str = "") -> tuple[str, str]:
    raw_cc = (tags.get("country") or tags.get("ISO3166-1") or tags.get("addr:country") or "").strip().lower()
    if len(raw_cc) == 2 and raw_cc in CC_TO_COUNTRY:
        return CC_TO_COUNTRY[raw_cc], raw_cc

    is_in = tags.get("is_in") or tags.get("location") or ""
    for cc, name in CC_TO_COUNTRY.items():
        if name.lower() in is_in.lower():
            return name, cc

    if fallback_cc:
        return fallback_country or CC_TO_COUNTRY.get(fallback_cc, fallback_country), fallback_cc
    return fallback_country, fallback_cc


def tips_from_tags(tags: dict) -> list[str]:
    tips: list[str] = []
    for key in ("description", "note", "information", "access"):
        value = tags.get(key)
        if value and isinstance(value, str):
            text = value.strip()
            if text and text not in tips:
                tips.append(text[:600])
    return tips[:6]


def load_discovered_cache() -> list[dict]:
    if not DISCOVERED_CACHE_PATH.exists():
        return []
    try:
        return json.loads(DISCOVERED_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_discovered_cache(rows: list[dict]) -> None:
    """Persist only Overpass-discovered rows (not base JSON seeds) for faster rebuilds."""
    entries = []
    seen: set[int] = set()
    for row in rows:
        osm_id = int(row.get("osm_id") or 0)
        if not osm_id or osm_id in seen:
            continue
        seen.add(osm_id)
        entries.append(
            {
                "osm_id": osm_id,
                "name": row["name"],
                "country": row["country"],
                "cc": row.get("cc", ""),
                "popularity": row.get("popularity", 55),
            }
        )
    DISCOVERED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERED_CACHE_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def build_hike_record(
    *,
    osm_id: int,
    name: str,
    country: str,
    cc: str,
    chains: list[list[list[float]]],
    tags: dict,
    seed_popularity: int | None = None,
) -> dict | None:
    chains = [list(c) for c in chains if len(c) >= 2]
    if not chains:
        return None

    chains = simplify_chains(chains)
    if not chains:
        return None

    length_km = round(total_length_km(chains), 1)
    if length_km < 3:
        return None

    west, south, east, north = bbox_from_chains(chains)
    lng, lat = centroid_of_chains(chains)
    popularity = seed_popularity if seed_popularity is not None else score_tags(tags, 50)
    if length_km > 80:
        popularity = min(100, popularity + 8)
    elif length_km > 40:
        popularity = min(100, popularity + 4)

    hike_id = f"europe-{osm_id}"
    network = tags.get("network") or tags.get("iwn") or ""
    ascent = tags.get("ascent") or tags.get("elevation:gain")
    try:
        ascent_m = int(float(ascent)) if ascent else None
    except (TypeError, ValueError):
        ascent_m = None

    summary = tags.get("description") or (
        f"{name} is a {length_km:.0f} km hiking route"
        f"{f' in {country}' if country else ''}, mapped from OpenStreetMap."
    )
    tips = tips_from_tags(tags)

    if len(chains) == 1:
        geometry = {"type": "LineString", "coordinates": chains[0]}
    else:
        geometry = {"type": "MultiLineString", "coordinates": chains}

    longest_chain = max(chains, key=line_length_km)
    start_lng, start_lat = longest_chain[0]
    end_lng, end_lat = longest_chain[-1]
    start_name = (tags.get("from") or "").strip() or None
    end_name = (tags.get("to") or "").strip() or None
    start_instructions = _build_start_instructions(
        name=name,
        country=country or tags.get("location:country") or "Europe",
        start_name=start_name,
        end_name=end_name,
        tags=tags,
        length_km=length_km,
    )

    return {
        "id": hike_id,
        "region_id": "europe",
        "osm_id": osm_id,
        "name": name,
        "country": country or tags.get("location:country") or "Europe",
        "cc": cc or "",
        "lat": lat,
        "lng": lng,
        "length_km": length_km,
        "ascent_m": ascent_m,
        "difficulty": difficulty_from_tags(tags),
        "network": network,
        "route_type": tags.get("route") or "hiking",
        "popularity": popularity,
        "tier": tier_from_popularity(popularity),
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "summary": summary[:1200],
        "tagline": (tags.get("ref") or (network.upper() if network else f"{length_km:.0f} km trail")),
        "tips_json": json.dumps(tips),
        "photos_json": "[]",
        "geometry_json": json.dumps(geometry),
        "source": "OpenStreetMap",
        "enriched": 0,
        "start_lat": start_lat,
        "start_lng": start_lng,
        "end_lat": end_lat,
        "end_lng": end_lng,
        "start_name": start_name,
        "end_name": end_name,
        "start_instructions": start_instructions,
    }


def _build_start_instructions(
    *,
    name: str,
    country: str,
    start_name: str | None,
    end_name: str | None,
    tags: dict,
    length_km: float,
) -> str:
    """Compose a one-paragraph 'where to typically start' note from OSM tags."""
    bits: list[str] = []
    if start_name:
        if end_name and end_name.lower() != start_name.lower():
            bits.append(
                f"Most walkers start the {name} in {start_name} and finish in {end_name}, "
                f"covering about {length_km:.0f} km."
            )
        else:
            bits.append(
                f"The traditional trailhead is in {start_name}; most walkers start there "
                f"and head out for the {length_km:.0f} km route."
            )
    else:
        bits.append(
            f"The {name} can be picked up at any of its waymarked entry points along the route; "
            f"the official mapped trailhead is shown on the trail card."
        )

    operator = (tags.get("operator") or "").strip()
    website = (tags.get("website") or "").strip()
    network = (tags.get("network") or "").upper()
    if operator:
        bits.append(f"The route is maintained by {operator}.")
    if network in {"IWN", "NWN", "RWN", "LWN"}:
        bits.append(
            "Look for the official waymark badge on signposts and trees — "
            "it appears on every waypoint along the way."
        )
    if website:
        bits.append(f"For up-to-date stage details and access notes, see {website}.")
    if country and country.lower() not in (start_name or "").lower():
        bits.append(
            f"Public transport to the trailhead is generally reliable across {country}, "
            "so most hikers arrive by train or bus."
        )

    return " ".join(bits).strip()


def write_legacy_geojson(rows: list[dict]) -> None:
    by_region: dict[str, list[dict]] = {}
    for row in rows:
        by_region.setdefault(row.get("region_id", "europe"), []).append(row)

    for region_id, region_rows in by_region.items():
        write_region_legacy_geojson(region_id, region_rows)


def write_region_legacy_geojson(region_id: str, rows: list[dict]) -> None:
    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lng"], row["lat"]]},
                "properties": {
                    "id": row["id"],
                    "name": row["name"],
                    "country": row["country"],
                    "cc": row["cc"],
                    "length_km": row["length_km"],
                    "popularity": row["popularity"],
                    "tier": row["tier"],
                    "tagline": row["tagline"],
                },
            }
        )
    legacy_geojson = ROOT / "Trip" / "hikes" / region_id / "hikes-index.geojson"
    legacy_geojson.parent.mkdir(parents=True, exist_ok=True)
    legacy_geojson.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def load_seed_files(*, montenegro_only: bool = False, include_montenegro: bool = True) -> list[dict]:
    seeds: list[dict] = []
    if not montenegro_only:
        seeds.extend(json.loads(SEED_PATH.read_text(encoding="utf-8")))
    if montenegro_only or include_montenegro:
        if MONTENEGRO_SEED_PATH.exists():
            seeds.extend(json.loads(MONTENEGRO_SEED_PATH.read_text(encoding="utf-8")))
    if not montenegro_only and CROATIA_SEED_PATH.exists():
        seeds.extend(json.loads(CROATIA_SEED_PATH.read_text(encoding="utf-8")))
    return seeds


def load_oceania_hikes() -> list[dict]:
    if not OCEANIA_SEED_PATH.is_file():
        return []
    payload = json.loads(OCEANIA_SEED_PATH.read_text(encoding="utf-8"))
    rows = []
    for entry in payload.get("hikes", []):
        coords = entry.get("geometry") or []
        if len(coords) < 2:
            continue
        chains = [coords]
        west, south, east, north = bbox_from_chains(chains)
        lng, lat = centroid_of_chains(chains)
        start_lng, start_lat = coords[0]
        end_lng, end_lat = coords[-1]
        geometry = {"type": "LineString", "coordinates": coords}
        rows.append(
            {
                "id": entry["id"],
                "region_id": "oceania",
                "osm_id": entry.get("osm_id"),
                "name": entry["name"],
                "country": entry.get("country") or "Oceania",
                "cc": (entry.get("cc") or "").lower(),
                "lat": lat,
                "lng": lng,
                "length_km": float(entry.get("length_km") or total_length_km(chains)),
                "ascent_m": entry.get("ascent_m"),
                "difficulty": entry.get("difficulty"),
                "network": entry.get("network") or "",
                "route_type": entry.get("route_type") or "hiking",
                "popularity": int(entry.get("popularity") or 70),
                "tier": entry.get("tier") or tier_from_popularity(int(entry.get("popularity") or 70)),
                "west": west,
                "south": south,
                "east": east,
                "north": north,
                "summary": entry.get("summary") or f"{entry['name']} hiking route.",
                "tagline": entry.get("tagline") or f"{float(entry.get('length_km') or 0):.0f} km trail",
                "tips_json": json.dumps(entry.get("tips") or [], ensure_ascii=False),
                "photos_json": json.dumps(entry.get("photos") or [], ensure_ascii=False),
                "geometry_json": json.dumps(geometry, ensure_ascii=False),
                "source": "curated",
                "enriched": 1,
                "start_lat": start_lat,
                "start_lng": start_lng,
                "end_lat": end_lat,
                "end_lng": end_lng,
                "start_name": entry.get("start_name"),
                "end_name": entry.get("end_name"),
                "start_instructions": entry.get("start_instructions"),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true", help="Fetch additional routes from Overpass")
    parser.add_argument(
        "--curated-only",
        action="store_true",
        help="Only curated seed files (no Overpass discovery)",
    )
    parser.add_argument(
        "--montenegro",
        action="store_true",
        help="Montenegro seeds + discover trails in Montenegro only",
    )
    parser.add_argument("--limit", type=int, default=200, help="Max discovered relations")
    parser.add_argument(
        "--min-discover-km",
        type=float,
        default=25.0,
        help="Minimum length for discovered trails without Wikidata/Wikipedia",
    )
    parser.add_argument("--sleep", type=float, default=0.8, help="Delay between relation fetches (seconds)")
    args = parser.parse_args()

    base_seeds = load_seed_files(montenegro_only=args.montenegro, include_montenegro=True)
    seed_file_osm_ids = {int(s["osm_id"]) for s in base_seeds}
    seeds = list(base_seeds)
    if not args.montenegro:
        cache_entries = load_discovered_cache()
        if cache_entries:
            print(f"Re-importing {len(cache_entries)} cached discovered trails…")
            seeds = seeds + cache_entries
    seen_ids: set[int] = set()
    hikes: list[dict] = []

    print(f"Fetching {len(seeds)} seeded trails…")
    for seed in seeds:
        osm_id = int(seed["osm_id"])
        if osm_id in seen_ids:
            continue
        seen_ids.add(osm_id)
        label = str(seed.get("name", "")).encode("ascii", errors="replace").decode("ascii")
        print(f"  relation {osm_id} {label}")
        payload = fetch_relation(osm_id)
        time.sleep(args.sleep)
        if not payload:
            continue
        record = build_hike_record(
            osm_id=osm_id,
            name=seed.get("name") or payload["tags"].get("name") or f"Trail {osm_id}",
            country=seed.get("country", "Europe"),
            cc=seed.get("cc", ""),
            chains=payload["chains"],
            tags=payload["tags"],
            seed_popularity=int(seed.get("popularity", 85)),
        )
        if record:
            hikes.append(record)

    if (args.discover or args.montenegro) and not args.curated_only:
        discover_bbox = MONTENEGRO_BBOX if args.montenegro else None
        discover_limit = args.limit if args.discover else 40
        if args.montenegro and not args.discover:
            discover_limit = min(args.limit, 40)
        for item in discover_relations(discover_limit, bbox=discover_bbox):
            osm_id = int(item["osm_id"])
            if osm_id in seen_ids:
                continue
            seen_ids.add(osm_id)
            tags = item.get("tags") or {}
            label = str(item.get("name", "")).encode("ascii", errors="replace").decode("ascii")
            print(f"  discover {osm_id} {label}")
            payload = fetch_relation(osm_id)
            time.sleep(args.sleep)
            if not payload:
                continue
            tags = payload["tags"]
            country, cc = country_from_tags(
                tags,
                fallback_country="Montenegro" if args.montenegro else "Europe",
                fallback_cc="me" if args.montenegro else "",
            )
            record = build_hike_record(
                osm_id=osm_id,
                name=item.get("name") or tags.get("name") or f"Trail {osm_id}",
                country=country,
                cc=cc,
                chains=payload["chains"],
                tags=tags,
            )
            if record and should_keep_discovered(
                tags, record, min_length_km=args.min_discover_km
            ):
                hikes.append(record)

    if not args.montenegro:
        hikes.extend(load_oceania_hikes())

    if not hikes:
        raise SystemExit("No hikes imported. Check network access to Overpass API.")

    before = len(hikes)
    hikes = dedupe_hikes(hikes)
    if before != len(hikes):
        print(f"Deduped catalog: {before} -> {len(hikes)} trails")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()

    region_counts: dict[str, int] = {}
    for row in hikes:
        region_counts[row.get("region_id", "europe")] = region_counts.get(row.get("region_id", "europe"), 0) + 1
    for region_id, count in region_counts.items():
        conn.execute(
            "INSERT INTO regions (id, label, hike_count) VALUES (?, ?, ?)",
            (region_id, REGION_LABELS.get(region_id, region_id.replace("-", " ").title()), count),
        )

    insert = """
        INSERT INTO hikes (
            id, region_id, osm_id, name, country, cc, lat, lng,
            length_km, ascent_m, difficulty, network, route_type,
            popularity, tier, west, south, east, north,
            summary, tagline, tips_json, photos_json, geometry_json, source, enriched,
            start_lat, start_lng, end_lat, end_lng,
            start_name, end_name, start_instructions, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    for row in hikes:
        conn.execute(
            insert,
            (
                row["id"],
                row["region_id"],
                row["osm_id"],
                row["name"],
                row["country"],
                row["cc"],
                row["lat"],
                row["lng"],
                row["length_km"],
                row["ascent_m"],
                row["difficulty"],
                row["network"],
                row["route_type"],
                row["popularity"],
                row["tier"],
                row["west"],
                row["south"],
                row["east"],
                row["north"],
                row["summary"],
                row["tagline"],
                row["tips_json"],
                row["photos_json"],
                row["geometry_json"],
                row["source"],
                row["enriched"],
                row.get("start_lat"),
                row.get("start_lng"),
                row.get("end_lat"),
                row.get("end_lng"),
                row.get("start_name"),
                row.get("end_name"),
                row.get("start_instructions"),
                now,
            ),
        )

    conn.commit()
    conn.close()

    write_legacy_geojson(hikes)

    manifest = {
        "schemaVersion": 1,
        "storage": "sqlite",
        "database": "./Trip/hikes/hikes.db",
        "apiBase": "/api/hikes",
        "source": "OpenStreetMap via Overpass API",
        "regions": [
            {
                "id": region_id,
                "label": REGION_LABELS.get(region_id, region_id.replace("-", " ").title()),
                "count": region_counts[region_id],
                "legacyGeojson": f"./Trip/hikes/{region_id}/hikes-index.geojson",
            }
            for region_id in sorted(region_counts.keys(), key=lambda item: 0 if item == "europe" else 1)
        ],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not args.montenegro:
        discovered_only = [h for h in hikes if int(h.get("osm_id") or 0) not in seed_file_osm_ids]
        save_discovered_cache(discovered_only)

    print(f"Wrote {len(hikes)} hikes to {DB_PATH}")


if __name__ == "__main__":
    main()
