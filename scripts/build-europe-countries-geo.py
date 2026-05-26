#!/usr/bin/env python3
"""Download simplified Europe country polygons for the map country selector."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Trip" / "geo" / "europe-countries.geojson"
SOURCE = "https://raw.githubusercontent.com/leakyMirror/map-of-europe/master/GeoJSON/europe.geojson"


def main() -> None:
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "Trailthread/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    features = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        cc = (props.get("ISO2") or "").strip().upper()
        name = (props.get("NAME") or "").strip()
        if not cc or not feature.get("geometry"):
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"cc": cc, "name": name},
                "geometry": feature["geometry"],
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(features)} countries to {OUT}")


if __name__ == "__main__":
    main()
