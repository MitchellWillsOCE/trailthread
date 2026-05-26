"""Shared helpers: national parks vs cities vs POI categories."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARKS_SEED = ROOT / "scripts" / "data" / "europe-parks-seed.json"

PARK_NAME_RE = re.compile(
    r"\b(national park|nature park|national reserve|national lakes|biosphere reserve)\b",
    re.IGNORECASE,
)


def load_park_names() -> set[str]:
    names: set[str] = set()
    if PARKS_SEED.is_file():
        for entry in json.loads(PARKS_SEED.read_text(encoding="utf-8")):
            name = (entry.get("name") or "").strip()
            if name:
                names.add(name.lower())
    return names


def is_park_place_name(name: str, park_names: set[str] | None = None) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    if park_names is None:
        park_names = load_park_names()
    lower = text.lower()
    if lower in park_names:
        return True
    return bool(PARK_NAME_RE.search(text))


def infer_poi_category(name: str) -> str:
    n = (name or "").lower()
    if any(
        token in n
        for token in (
            "fortress",
            " fort ",
            "castle",
            " citadel",
            "kula",
            "fort ",
            "fort.",
        )
    ):
        return "fortress"
    if any(
        token in n
        for token in (
            "mount ",
            " mountain",
            " peak",
            " summit",
            "volcano",
            "mont blanc",
            "matterhorn",
        )
    ):
        return "mountain"
    if any(
        token in n
        for token in (
            "cathedral",
            "basilica",
            "imperial city",
            "old town",
            "old district",
            "palace",
            "monastery",
            "temple",
            "mosque",
            "museum",
            "bridge",
            "cave",
        )
    ):
        return "monument"
    return "heritage"
