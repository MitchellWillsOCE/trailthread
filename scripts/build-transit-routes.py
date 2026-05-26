#!/usr/bin/env python3
"""
Build journey transit (rail) geometries from OpenStreetMap train relations and railway lines.

Usage:
  python scripts/build-transit-routes.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = ROOT / "scripts" / "data" / "journey-transit-seeds.json"
OUT_PATH = ROOT / "Trip" / "transit-routes.json"

spec = importlib.util.spec_from_file_location("ferry_build", ROOT / "scripts" / "build-ferry-routes.py")
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

build = fb.build


def fetch_rail_ways_in_bbox(south: float, west: float, north: float, east: float) -> list[list[tuple[float, float]]]:
    q = (
        f"[out:json][timeout:120];("
        f'way["railway"~"rail|highspeed|light_rail"]({south},{west},{north},{east});'
        f'way["railway"="rail"]["service"!~"yard|siding|spur"]({south},{west},{north},{east});'
        f");out geom tags;"
    )
    data = build.http_post(q)
    segments: list[list[tuple[float, float]]] = []
    seen: set[int] = set()
    for el in data.get("elements", []):
        if el.get("type") != "way" or el.get("id") in seen:
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        tags = el.get("tags") or {}
        if tags.get("construction") or tags.get("abandoned") == "yes":
            continue
        pts = [(p["lon"], p["lat"]) for p in geom if "lat" in p and "lon" in p]
        if len(pts) >= 2:
            seen.add(el["id"])
            segments.append(pts)
    return segments


def nearest_point_on_segments(
    segments: list[list[tuple[float, float]]], point: tuple[float, float], max_km: float
) -> tuple[tuple[float, float], float] | None:
    best_pt = None
    best_d = max_km
    for seg in segments:
        for pt in seg:
            d = fb.dist_km(point, pt)
            if d < best_d:
                best_d = d
                best_pt = pt
    if best_pt is None:
        return None
    return best_pt, best_d


class RailGraph(fb.FerryGraph):
    """Rail network graph with explicit port-to-track spurs."""

    def link_port(self, port: tuple[float, float], rail_point: tuple[float, float]) -> None:
        a = self._node_id(port)
        b = self._node_id(rail_point)
        if a != b:
            self._add_edge(a, b)


def build_rail_segment(
    start: tuple[float, float],
    end: tuple[float, float],
    bbox: list[float],
    *,
    port_link_km: float = 4.0,
    snap_km: float = 0.35,
) -> list[tuple[float, float]]:
    south, west, north, east = bbox
    segments = fetch_rail_ways_in_bbox(south, west, north, east)
    if not segments:
        return []

    graph = RailGraph(segments, snap_km=snap_km)
    for port in (start, end):
        hit = nearest_point_on_segments(segments, port, port_link_km)
        if hit:
            graph.link_port(port, hit[0])

    return fb.route_through_graph([start, end], graph)


def build_relation_segment(
    relation_id: int,
    start: tuple[float, float],
    end: tuple[float, float],
) -> list[tuple[float, float]]:
    payload = build.fetch_relation(int(relation_id))
    if not payload or len(payload.get("coordinates", [])) < 2:
        return []
    coords = [(c[0], c[1]) for c in payload["coordinates"]]
    return fb.extract_subpath(coords, start, end)


def chain_segments(parts: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    chain: list[tuple[float, float]] = []
    for part in parts:
        if len(part) < 2:
            continue
        if not chain:
            chain.extend(part)
            continue
        if fb.dist_km(chain[-1], part[0]) < 0.15:
            chain.extend(part[1:])
        elif fb.dist_km(chain[-1], part[-1]) < 0.15:
            chain.extend(list(reversed(part))[1:])
        else:
            chain.extend(part)
    return chain


def build_route(seed: dict) -> list[tuple[float, float]]:
    parts: list[list[tuple[float, float]]] = []
    for segment in seed.get("segments", []):
        start = tuple(segment["from"])
        end = tuple(segment["to"])
        if segment.get("osm_relation_id"):
            part = build_relation_segment(int(segment["osm_relation_id"]), start, end)
        elif segment.get("rail_bbox"):
            part = build_rail_segment(start, end, segment["rail_bbox"])
        else:
            part = []
        if len(part) >= 2:
            parts.append(part)

    return chain_segments(parts)


def main() -> None:
    if not SEEDS_PATH.exists():
        print(f"Missing {SEEDS_PATH}")
        sys.exit(1)

    seeds = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    catalog: dict = {
        "schemaVersion": 1,
        "source": "OpenStreetMap rail network",
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "routes": {},
    }

    for seed in seeds:
        route_id = seed["id"]
        print(f"Building {route_id}…")
        coords = build_route(seed)
        if len(coords) < 2:
            print(f"  WARN: no geometry for {route_id}")
            continue

        coords = fb.simplify_coords(coords, min_m=100)
        length_km = round(build.line_length_km(coords), 1)
        catalog["routes"][route_id] = {
            "name": seed.get("name", route_id),
            "mode": seed.get("mode", "train"),
            "source": "OpenStreetMap rail network",
            "lengthKm": length_km,
            "coordinates": [[lng, lat] for lng, lat in coords],
        }
        print(f"  OK {length_km} km, {len(coords)} points")

    OUT_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(catalog['routes'])} routes)")


if __name__ == "__main__":
    main()
