#!/usr/bin/env python3
"""Build Europe city catalog: GeoJSON map layer + details index."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from place_kinds import is_park_place_name, load_park_names  # noqa: E402
SEED_PATH = ROOT / "scripts" / "data" / "europe-cities-seed.json"
TRIP_COORDS_PATH = ROOT / "scripts" / "data" / "trip-place-coordinates.json"
PLACE_DETAILS_PATH = ROOT / "Trip" / "place-details.json"
CACHE_DIR = ROOT / "scripts" / "cache"
GEONAMES_ZIP_URL = "https://download.geonames.org/export/dump/cities15000.zip"
OUT_DIR = ROOT / "Trip" / "cities" / "europe"
MANIFEST_PATH = ROOT / "Trip" / "cities" / "manifest.json"

EUROPE_COUNTRIES = {
    "Albania",
    "Armenia",
    "Austria",
    "Belgium",
    "Bosnia and Herzegovina",
    "Bulgaria",
    "Croatia",
    "Czech Republic",
    "Denmark",
    "Estonia",
    "Finland",
    "France",
    "Georgia",
    "Germany",
    "Gibraltar",
    "Greece",
    "Hungary",
    "Iceland",
    "Ireland",
    "Italy",
    "Latvia",
    "Lithuania",
    "Luxembourg",
    "Malta",
    "Monaco",
    "Montenegro",
    "Netherlands",
    "North Macedonia",
    "Norway",
    "Poland",
    "Portugal",
    "Romania",
    "Russia",
    "Serbia",
    "Slovenia",
    "Spain",
    "Sweden",
    "Switzerland",
    "Turkey",
    "Ukraine",
    "United Kingdom",
}

EUROPE_CC = {
    "AL",
    "AD",
    "AM",
    "AT",
    "AZ",
    "BY",
    "BE",
    "BA",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "GE",
    "DE",
    "GR",
    "HU",
    "IS",
    "IE",
    "IT",
    "XK",
    "LV",
    "LI",
    "LT",
    "LU",
    "MT",
    "MD",
    "MC",
    "ME",
    "NL",
    "MK",
    "NO",
    "PL",
    "PT",
    "RO",
    "RU",
    "SM",
    "RS",
    "SK",
    "SI",
    "ES",
    "SE",
    "CH",
    "TR",
    "UA",
    "GB",
    "GI",
    "VA",
}

CC_TO_COUNTRY = {
    "AL": "Albania",
    "AD": "Andorra",
    "AM": "Armenia",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BY": "Belarus",
    "BE": "Belgium",
    "BA": "Bosnia and Herzegovina",
    "BG": "Bulgaria",
    "HR": "Croatia",
    "CY": "Cyprus",
    "CZ": "Czech Republic",
    "DK": "Denmark",
    "EE": "Estonia",
    "FI": "Finland",
    "FR": "France",
    "GE": "Georgia",
    "DE": "Germany",
    "GR": "Greece",
    "HU": "Hungary",
    "IS": "Iceland",
    "IE": "Ireland",
    "IT": "Italy",
    "XK": "Kosovo",
    "LV": "Latvia",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MT": "Malta",
    "MD": "Moldova",
    "MC": "Monaco",
    "ME": "Montenegro",
    "NL": "Netherlands",
    "MK": "North Macedonia",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RU": "Russia",
    "SM": "San Marino",
    "RS": "Serbia",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "ES": "Spain",
    "SE": "Sweden",
    "CH": "Switzerland",
    "TR": "Turkey",
    "UA": "Ukraine",
    "GB": "United Kingdom",
    "GI": "Gibraltar",
    "VA": "Vatican City",
}

COUNTRY_TO_CC = {v: k for k, v in CC_TO_COUNTRY.items() if v in EUROPE_COUNTRIES or k in EUROPE_CC}


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "city"


def city_id(name: str, cc: str) -> str:
    return f"{slugify(name)}-{cc.lower()}"


def tier_from_population(pop: int) -> str:
    if pop >= 1_000_000:
        return "major"
    if pop >= 100_000:
        return "regional"
    return "town"


def stub_detail(row: dict) -> dict:
    name = row["name"]
    country = row["country"]
    return {
        "id": row["id"],
        "name": name,
        "country": country,
        "cc": row["cc"],
        "lat": row["lat"],
        "lng": row["lng"],
        "general": f"{name} is a destination in {country} — open for a future deep-dive story card.",
        "activities": [
            "Old town walk",
            "Local food market",
            "Viewpoint sunset",
        ],
        "tips": [
            "Check seasonal opening hours for major sights",
            "Book accommodation early in peak season",
        ],
        "tagline": f"Discover {name}",
        "photos": [],
        "source": row.get("source", "catalog"),
    }


def merge_place_detail(base: dict, place: dict, name: str) -> dict:
    merged = {**base, **place}
    merged["id"] = base["id"]
    merged["name"] = name
    merged["cc"] = base["cc"]
    merged["lat"] = base["lat"]
    merged["lng"] = base["lng"]
    merged["source"] = "trip"
    if not merged.get("tagline"):
        activities = merged.get("activities") or []
        if activities:
            merged["tagline"] = activities[0]
        elif merged.get("general"):
            text = merged["general"]
            merged["tagline"] = text if len(text) <= 72 else f"{text[:69].rsplit(' ', 1)[0]}…"
    return merged


def load_geonames_rows(min_population: int = 15000) -> list[dict]:
    cache_zip = CACHE_DIR / "cities15000.zip"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not cache_zip.exists():
        print(f"Downloading GeoNames cities15000 from {GEONAMES_ZIP_URL} …")
        with urlopen(GEONAMES_ZIP_URL, timeout=120) as response:
            cache_zip.write_bytes(response.read())

    rows: list[dict] = []
    with zipfile.ZipFile(cache_zip) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".txt"))
        with archive.open(name) as handle:
            for raw in handle:
                line = raw.decode("utf-8").rstrip("\n")
                parts = line.split("\t")
                if len(parts) < 15:
                    continue
                cc = parts[8]
                if cc not in EUROPE_CC:
                    continue
                try:
                    pop = int(parts[14] or 0)
                except ValueError:
                    pop = 0
                if pop < min_population:
                    continue
                name = parts[1] or parts[2]
                country = CC_TO_COUNTRY.get(cc, cc)
                rows.append(
                    {
                        "name": name,
                        "country": country,
                        "cc": cc,
                        "lat": float(parts[4]),
                        "lng": float(parts[5]),
                        "pop": pop,
                        "tier": tier_from_population(pop),
                        "source": "geonames",
                    }
                )
    print(f"GeoNames: {len(rows)} European cities (pop >= {min_population})")
    return rows


def add_row(by_id: dict[str, dict], row: dict, *, prefer: bool = False) -> None:
    cid = city_id(row["name"], row["cc"])
    row = {**row, "id": cid}
    existing = by_id.get(cid)
    if existing is None or prefer or existing.get("source") == "geonames":
        by_id[cid] = row


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Europe city catalog")
    parser.add_argument(
        "--geonames",
        action="store_true",
        help="Merge GeoNames cities15000 (European, pop >= 15k)",
    )
    parser.add_argument(
        "--min-pop",
        type=int,
        default=15000,
        help="Minimum population for GeoNames import (default 15000)",
    )
    args = parser.parse_args()

    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    trip_coords = json.loads(TRIP_COORDS_PATH.read_text(encoding="utf-8"))
    place_details = json.loads(PLACE_DETAILS_PATH.read_text(encoding="utf-8"))

    by_id: dict[str, dict] = {}

    if args.geonames:
        for row in load_geonames_rows(args.min_pop):
            add_row(by_id, row)

    for row in seed:
        add_row(by_id, row, prefer=True)

    for name, coords in trip_coords.items():
        row = {
            "name": name,
            "country": coords["country"],
            "cc": coords["cc"],
            "lat": coords["lat"],
            "lng": coords["lng"],
            "pop": coords.get("pop", 5000),
            "tier": coords.get("tier", "town"),
            "source": "trip-coords",
        }
        add_row(by_id, row, prefer=True)

    for name, place in place_details.items():
        country = place.get("country", "")
        if country not in EUROPE_COUNTRIES:
            continue
        cc = COUNTRY_TO_CC.get(country, "EU")
        if name in trip_coords:
            continue
        key = city_id(name, cc)
        if key in by_id:
            continue
        if name.lower() in {r["name"].lower() for r in by_id.values()}:
            continue
        continue

    park_names = load_park_names()
    features = []
    details: dict[str, dict] = {}

    for row in sorted(by_id.values(), key=lambda r: (r["country"], r["name"])):
        if is_park_place_name(row["name"], park_names):
            continue
        cid = row["id"]
        props = {
            "id": cid,
            "name": row["name"],
            "country": row["country"],
            "cc": row["cc"],
            "pop": row.get("pop", 0),
            "tier": row.get("tier", "town"),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lng"], row["lat"]]},
                "properties": props,
            }
        )
        base = stub_detail({**row, "id": cid})
        place = place_details.get(row["name"])
        if place:
            details[cid] = merge_place_detail(base, place, row["name"])
        else:
            details[cid] = base

    geojson = {"type": "FeatureCollection", "features": features}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "cities.geojson").write_text(
        json.dumps(geojson, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "details.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    manifest = {
        "schemaVersion": 1,
        "regions": [
            {
                "id": "europe",
                "label": "Europe",
                "geojson": "./Trip/cities/europe/cities.geojson",
                "details": "./Trip/cities/europe/details.json",
                "count": len(features),
                "sources": ["seed", "trip-coords", "geonames"] if args.geonames else ["seed", "trip-coords"],
            }
        ],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {len(features)} European cities to {OUT_DIR}")
    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
