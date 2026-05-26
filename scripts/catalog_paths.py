"""Canonical SQLite paths for catalog databases."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_catalog_db(base: Path) -> Path:
    """Use primary DB; prefer `.new` only when primary is missing."""
    new_path = Path(f"{base}.new")
    if not base.is_file() and new_path.is_file():
        return new_path
    return base


CITIES_DB = resolve_catalog_db(ROOT / "Trip" / "cities" / "cities.db")
PARKS_DB = resolve_catalog_db(ROOT / "Trip" / "parks" / "parks.db")
HIKES_DB = resolve_catalog_db(ROOT / "Trip" / "hikes" / "hikes.db")
POI_DB = resolve_catalog_db(ROOT / "Trip" / "poi" / "poi.db")
