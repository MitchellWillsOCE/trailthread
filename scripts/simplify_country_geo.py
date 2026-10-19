#!/usr/bin/env python3
"""Simplify country border GeoJSON for the map overlay, in place.

Borders only render up to zoom 8, where one screen pixel is about 0.005
degrees, so finer detail costs download and projection time without
showing up on screen.

Usage: python scripts/simplify_country_geo.py Trip/geo/europe-countries.geojson [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOLERANCE_DEG = 0.004
DECIMALS = 4


def _perp_dist_sq(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _douglas_peucker(points, tol_sq):
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        best, index = 0.0, -1
        for i in range(start + 1, end):
            d = _perp_dist_sq(points[i], points[start], points[end])
            if d > best:
                best, index = d, i
        if index != -1 and best > tol_sq:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [p for p, k in zip(points, keep) if k]


def _round_ring(ring):
    out = []
    for x, y, *_ in ring:
        p = [round(x, DECIMALS), round(y, DECIMALS)]
        if not out or out[-1] != p:
            out.append(p)
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out


def simplify_ring(ring, *, is_hole: bool):
    rounded = _round_ring(ring)
    if len(rounded) < 4:
        return None if is_hole else rounded
    simplified = _douglas_peucker(rounded, TOLERANCE_DEG * TOLERANCE_DEG)
    if len(simplified) >= 4:
        return simplified
    # Tiny islands and microstates collapse under the tolerance; keep them visible.
    return None if is_hole else rounded


def simplify_polygon(rings):
    out = []
    for i, ring in enumerate(rings):
        simplified = simplify_ring(ring, is_hole=i > 0)
        if simplified and len(simplified) >= 4:
            out.append(simplified)
        elif i == 0:
            return None
    return out


def simplify_geometry(geometry):
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Polygon":
        polygon = simplify_polygon(coords)
        return {"type": "Polygon", "coordinates": polygon} if polygon else geometry
    if kind == "MultiPolygon":
        polygons = [p for p in (simplify_polygon(rings) for rings in coords) if p]
        return {"type": "MultiPolygon", "coordinates": polygons} if polygons else geometry
    return geometry


def simplify_collection(data: dict) -> dict:
    for feature in data.get("features", []):
        if feature.get("geometry"):
            feature["geometry"] = simplify_geometry(feature["geometry"])
    return data


def simplify_file(path: Path) -> None:
    before = path.stat().st_size
    data = json.loads(path.read_text(encoding="utf-8"))
    simplify_collection(data)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{path}: {before // 1024} KB -> {path.stat().st_size // 1024} KB")


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    for arg in argv:
        simplify_file(Path(arg))


if __name__ == "__main__":
    main(sys.argv[1:])
