#!/usr/bin/env python3
"""
Build journey ferry geometries from OpenStreetMap ferry ways/relations.

Usage:
  python scripts/build-ferry-routes.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from heapq import heappop, heappush
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = ROOT / "scripts" / "data" / "journey-ferry-seeds.json"
OUT_PATH = ROOT / "Trip" / "ferry-routes.json"

spec = importlib.util.spec_from_file_location("build_hikes", ROOT / "scripts" / "build-hikes-db.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def dist_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a[1], a[0]
    lat2, lon2 = b[1], b[0]
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lon2 - lon1)
    x = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def fetch_ferry_ways_in_bbox(south: float, west: float, north: float, east: float) -> list[dict]:
    q = (
        f"[out:json][timeout:120];("
        f'way["route"="ferry"]({south},{west},{north},{east});'
        f'way["ferry"="yes"]({south},{west},{north},{east});'
        f");out geom tags;"
    )
    data = build.http_post(q)
    segments: list[dict] = []
    for el in data.get("elements", []):
        geom = el.get("geometry")
        if not geom:
            continue
        pts = [(p["lon"], p["lat"]) for p in geom if "lat" in p and "lon" in p]
        if len(pts) >= 2:
            segments.append({"id": el["id"], "name": (el.get("tags") or {}).get("name", ""), "coords": pts})
    return segments


def fetch_way_geom(way_id: int) -> list[tuple[float, float]]:
    q = f"[out:json][timeout:60];way({way_id});out geom tags;"
    data = build.http_post(q)
    for el in data.get("elements", []):
        if el.get("type") == "way" and el.get("geometry"):
            pts = [(p["lon"], p["lat"]) for p in el["geometry"] if "lat" in p and "lon" in p]
            if len(pts) >= 2:
                return pts
    return []


def simplify_coords(coords: list[tuple[float, float]], min_m: float = 80) -> list[tuple[float, float]]:
    if len(coords) < 3:
        return coords
    out = [coords[0]]
    for pt in coords[1:]:
        if dist_km(out[-1], pt) * 1000 >= min_m:
            out.append(pt)
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


class FerryGraph:
    def __init__(self, segments: list[list[tuple[float, float]]], *, snap_km: float = 0.12):
        self.nodes: list[tuple[float, float]] = []
        self.adj: dict[int, list[tuple[int, float]]] = defaultdict(list)
        self._snap_km = snap_km
        for seg in segments:
            self._add_segment(seg)

    def _node_id(self, pt: tuple[float, float]) -> int:
        for i, existing in enumerate(self.nodes):
            if dist_km(existing, pt) <= self._snap_km:
                return i
        self.nodes.append(pt)
        return len(self.nodes) - 1

    def _add_edge(self, a: int, b: int) -> None:
        w = dist_km(self.nodes[a], self.nodes[b])
        if w < 1e-6:
            return
        self.adj[a].append((b, w))
        self.adj[b].append((a, w))

    def _add_segment(self, coords: list[tuple[float, float]]) -> None:
        ids = [self._node_id(pt) for pt in coords]
        for i in range(len(ids) - 1):
            if ids[i] != ids[i + 1]:
                self._add_edge(ids[i], ids[i + 1])

    def nearest(self, point: tuple[float, float], max_km: float = 8) -> int | None:
        best = None
        best_d = max_km
        for i, node in enumerate(self.nodes):
            d = dist_km(node, point)
            if d < best_d:
                best_d = d
                best = i
        return best

    def shortest_path(self, start: int, end: int) -> list[int] | None:
        if start == end:
            return [start]
        dist = {start: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, start)]
        seen = set()
        while heap:
            d, u = heappop(heap)
            if u in seen:
                continue
            seen.add(u)
            if u == end:
                path = [end]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for v, w in self.adj.get(u, []):
                nd = d + w
                if v not in dist or nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heappush(heap, (nd, v))
        return None

    def path_coords(self, node_ids: list[int]) -> list[tuple[float, float]]:
        if not node_ids:
            return []
        return [self.nodes[i] for i in node_ids]


def extract_subpath(coords: list[tuple[float, float]], start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    if len(coords) < 2:
        return coords

    def nearest_index(point: tuple[float, float]) -> int:
        return min(range(len(coords)), key=lambda i: dist_km(coords[i], point))

    i0 = nearest_index(start)
    i1 = nearest_index(end)
    if i0 <= i1:
        segment = coords[i0 : i1 + 1]
    else:
        segment = list(reversed(coords[i1 : i0 + 1]))
    if dist_km(segment[0], start) > 0.3:
        segment = [start, *segment]
    if dist_km(segment[-1], end) > 0.3:
        segment = [*segment, end]
    return segment


def route_through_graph(ports: list[tuple[float, float]], graph: FerryGraph) -> list[tuple[float, float]]:
    chain: list[tuple[float, float]] = []
    for i in range(len(ports) - 1):
        a, b = ports[i], ports[i + 1]
        na = graph.nearest(a, max_km=12)
        nb = graph.nearest(b, max_km=12)
        if na is None or nb is None:
            return []
        path = graph.shortest_path(na, nb)
        if not path:
            return []
        seg = graph.path_coords(path)
        if chain and dist_km(chain[-1], seg[0]) < 0.05:
            seg = seg[1:]
        chain.extend(seg)
    return chain


def build_from_osm_ways(way_ids: list[int], ports: list[tuple[float, float]]) -> list[tuple[float, float]]:
    segments: list[list[tuple[float, float]]] = []
    for wid in way_ids:
        coords = fetch_way_geom(int(wid))
        if len(coords) >= 2:
            segments.append(coords)
    if not segments:
        return []
    merged = build.stitch_segments(segments)
    if len(merged) >= 2 and len(ports) >= 2:
        return extract_subpath(merged, ports[0], ports[-1])
    graph = FerryGraph(segments, snap_km=0.15)
    return route_through_graph(ports, graph)


def build_from_bbox(ports: list[tuple[float, float]], bbox: list[float]) -> list[tuple[float, float]]:
    south, west, north, east = bbox
    ways = fetch_ferry_ways_in_bbox(south, west, north, east)
    segments = [w["coords"] for w in ways]
    if not segments:
        return []
    graph = FerryGraph(segments, snap_km=0.18)
    routed = route_through_graph(ports, graph)
    return routed


def build_from_relation(relation_id: int, ports: list[tuple[float, float]]) -> list[tuple[float, float]]:
    payload = build.fetch_relation(int(relation_id))
    if not payload or len(payload.get("coordinates", [])) < 2:
        return []
    coords = [(c[0], c[1]) for c in payload["coordinates"]]
    if len(ports) >= 2:
        return extract_subpath(coords, ports[0], ports[-1])
    return coords


def interpolate_segment(a: tuple[float, float], b: tuple[float, float], steps: int) -> list[tuple[float, float]]:
    if steps < 2:
        return [a, b]
    result = []
    for i in range(steps):
        t = i / (steps - 1)
        result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return result


def build_from_waypoints(waypoints: list[list[float]], ports: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = [ports[0]] if ports else []
    pts.extend((float(p[0]), float(p[1])) for p in waypoints)
    if ports and len(ports) > 1:
        pts.append(ports[-1])
    chain: list[tuple[float, float]] = []
    for i in range(len(pts) - 1):
        steps = max(6, int(dist_km(pts[i], pts[i + 1]) * 4))
        seg = interpolate_segment(pts[i], pts[i + 1], steps)
        chain = seg if not chain else [*chain, *seg[1:]]
    return chain


def main() -> None:
    if not SEEDS_PATH.exists():
        print(f"Missing {SEEDS_PATH}")
        sys.exit(1)

    seeds = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    catalog: dict = {
        "schemaVersion": 1,
        "source": "OpenStreetMap ferry routes",
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "routes": {},
    }

    for seed in seeds:
        route_id = seed["id"]
        name = seed.get("name", route_id)
        ports = [(float(p[0]), float(p[1])) for p in seed["ports"]]
        coords: list[tuple[float, float]] = []

        print(f"Building {route_id}…")
        if seed.get("osm_relation_id"):
            coords = build_from_relation(int(seed["osm_relation_id"]), ports)
        if len(coords) < 2 and seed.get("osm_way_ids"):
            coords = build_from_osm_ways([int(w) for w in seed["osm_way_ids"]], ports)
        if len(coords) < 2 and seed.get("bbox"):
            coords = build_from_bbox(ports, seed["bbox"])
        if len(coords) < 2 and seed.get("waypoints"):
            coords = build_from_waypoints(seed["waypoints"], ports)

        if len(coords) < 2:
            print(f"  WARN: no geometry for {route_id}")
            continue

        coords = simplify_coords(coords, min_m=120)
        length_km = round(build.line_length_km(coords), 1)
        catalog["routes"][route_id] = {
            "name": name,
            "source": "OpenStreetMap ferry network",
            "lengthKm": length_km,
            "coordinates": [[lng, lat] for lng, lat in coords],
        }
        print(f"  OK {length_km} km, {len(coords)} points")

    OUT_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(catalog['routes'])} routes)")


if __name__ == "__main__":
    main()
