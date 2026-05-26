#!/usr/bin/env python3
"""Remove national-park entries from the Europe cities GeoJSON + details."""

from __future__ import annotations

import json
from pathlib import Path

from place_kinds import is_park_place_name, load_park_names

ROOT = Path(__file__).resolve().parents[1]
GEOJSON = ROOT / "Trip" / "cities" / "europe" / "cities.geojson"
DETAILS = ROOT / "Trip" / "cities" / "europe" / "details.json"


def main() -> None:
    park_names = load_park_names()
    geojson = json.loads(GEOJSON.read_text(encoding="utf-8"))
    details = json.loads(DETAILS.read_text(encoding="utf-8")) if DETAILS.is_file() else {}

    kept_features = []
    removed_names: list[str] = []
    for feature in geojson.get("features", []):
        name = (feature.get("properties") or {}).get("name", "")
        if is_park_place_name(name, park_names):
            removed_names.append(name)
            cid = (feature.get("properties") or {}).get("id")
            if cid and cid in details:
                del details[cid]
            continue
        kept_features.append(feature)

    for cid, detail in list(details.items()):
        name = detail.get("name", "")
        if is_park_place_name(name, park_names):
            removed_names.append(name)
            del details[cid]

    geojson["features"] = kept_features
    GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False) + "\n", encoding="utf-8")
    DETAILS.write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Removed {len(removed_names)} park place(s) from cities catalog:")
    for name in sorted(set(removed_names)):
        print(f"  - {name}")
    print(f"Remaining cities: {len(kept_features)}")


if __name__ == "__main__":
    main()
