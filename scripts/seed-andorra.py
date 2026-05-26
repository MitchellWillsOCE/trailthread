"""Seed Andorra: cities (promote capital to major + add parishes), POIs, parks.

Idempotent — safe to run multiple times. Writes both the live SQLite catalogs
and the supporting JSON / GeoJSON source files so future rebuilds keep the
additions.

After running, run:
    python scripts/classify-places.py --apply
    python scripts/apply-place-activities.py --apply
    python scripts/consolidate-catalog-dbs.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog_paths import CITIES_DB, PARKS_DB, POI_DB  # noqa: E402

CITIES_GEOJSON = ROOT / "Trip" / "cities" / "europe" / "cities.geojson"

NOW_ISO = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Curated Andorran data
# ---------------------------------------------------------------------------

ANDORRA_CITIES = [
    # id, name, lat, lng, pop, tier, category, locale
    ("andorra-la-vella-ad",   "Andorra la Vella",   42.5078, 1.5211, 20430, "major",    "capital", "mountain"),
    ("les-escaldes-ad",       "les Escaldes",       42.5074, 1.5341, 15853, "regional", "town",    "mountain"),
    ("encamp-ad",             "Encamp",             42.5346, 1.5836, 13000, "regional", "town",    "mountain"),
    ("la-massana-ad",         "La Massana",         42.5450, 1.5147, 11000, "town",     "town",    "mountain"),
    ("sant-julia-de-loria-ad","Sant Julià de Lòria",42.4639, 1.4914,  9000, "town",     "town",    "mountain"),
    ("canillo-ad",            "Canillo",            42.5675, 1.5972,  6000, "town",     "village", "mountain"),
    ("ordino-ad",             "Ordino",             42.5564, 1.5333,  5000, "town",     "village", "mountain"),
    ("soldeu-ad",             "Soldeu",             42.5764, 1.6678,   900, "town",     "village", "mountain"),
    ("pas-de-la-casa-ad",     "Pas de la Casa",     42.5439, 1.7333,  2300, "town",     "village", "mountain"),
]

ANDORRA_POIS = [
    # name, lat, lng, category, popularity, tagline, summary
    (
        "Madriu-Perafita-Claror Valley", 42.4833, 1.5833, "heritage", 94,
        "UNESCO glacial valley of stone shepherds' huts and Pyrenean meadows",
        "The Madriu-Perafita-Claror Valley is Andorra's only UNESCO World Heritage Site, "
        "a 4,247 ha cultural landscape preserving stone shepherds' huts, terraced fields, "
        "and high pastures that have shaped Pyrenean life for nearly a millennium. "
        "Access is on foot only, from Escaldes-Engordany, Encamp, or Sant Julià.",
    ),
    (
        "Coma Pedrosa", 42.5928, 1.4581, "mountain", 86,
        "Andorra's highest summit (2,942 m) above Comapedrosa Natural Park",
        "Coma Pedrosa is the highest peak in Andorra at 2,942 m, the centrepiece of the "
        "Comapedrosa Valleys Natural Park. The summit hike from Arinsal climbs through "
        "alpine lakes and granite cirques and is best attempted between July and September.",
    ),
    (
        "Casa de la Vall", 42.5064, 1.5215, "heritage", 82,
        "16th-century parliament house of the co-principality in old Andorra la Vella",
        "Built in 1580 as a fortified manor, Casa de la Vall served as the seat of the "
        "Consell General — Andorra's parliament — from 1702 until 2011 and is one of "
        "the smallest historic parliaments in the world. Free guided visits show the "
        "council chamber, the chapel, and the iron Cabinet of Seven Keys.",
    ),
    (
        "Santa Coloma Church", 42.4934, 1.4963, "monument", 80,
        "Pre-Romanesque church (9th c.) with frescoes — oldest in Andorra",
        "Santa Coloma is the oldest preserved church in Andorra, with a 9th-century "
        "pre-Romanesque core, a rare four-storey cylindrical bell tower added in the "
        "12th century, and Lombard wall paintings now displayed on rotating projections.",
    ),
    (
        "Sant Joan de Caselles", 42.5713, 1.6532, "monument", 80,
        "Romanesque hillside chapel above Canillo with rare 12th-c. wooden Christ",
        "Set on a meadow above Canillo, Sant Joan de Caselles is one of the best-preserved "
        "Romanesque churches in Andorra. A three-storey bell tower, lime-washed nave, "
        "and a 12th-century polychrome wooden Christ above the altar make it a small "
        "Andorran masterpiece.",
    ),
    (
        "Roc del Quer Skywalk", 42.5694, 1.6098, "landmark", 81,
        "Cantilevered glass walkway 500 m above Vall d'Orient",
        "A 20-metre cantilevered platform with a glass-floor section juts out over a "
        "500 m drop into the Vall d'Orient. The 2 km approach trail from Prat Primer is "
        "easy and rewards visitors with views from the Madriu valley to the French border.",
    ),
    (
        "Sant Climent de Pal", 42.5503, 1.4694, "monument", 76,
        "Quiet Romanesque mountain church in the parish of la Massana",
        "Sant Climent stands above the hamlet of Pal at 1,550 m, a 12th-century Romanesque "
        "church with a slate-roofed bell tower typical of the central Pyrenees. The "
        "surrounding stone-built hamlet is among Andorra's best-preserved.",
    ),
    (
        "Caldea", 42.5083, 1.5394, "landmark", 78,
        "Mountain-spa cathedral of glass — the Pyrenees' largest thermal centre",
        "Designed by Jean-Michel Ruols and opened in 1994, Caldea is the largest thermal "
        "spa complex in southern Europe. Its mirrored glass tower has become an "
        "architectural landmark of Escaldes-Engordany, fed by natural sulphurous water "
        "at 70 °C from the local Pyrenean springs.",
    ),
    (
        "Sant Martí de la Cortinada", 42.5825, 1.5306, "monument", 74,
        "Romanesque parish church preserving Andorran medieval frescoes",
        "The 12th-century parish church of Ordino preserves Romanesque frescoes by the "
        "Master of la Cortinada, a striking late-Romanesque cycle hidden behind the "
        "Baroque altar until 1968.",
    ),
]

ANDORRA_PARKS = [
    # name, lat, lng, area_km2, biodiversity, popularity, stay, category, tagline, summary
    (
        "Sorteny Valley Natural Park", 42.6206, 1.6011, 11, 5, 80, "1 day", "mountain-park",
        "Alpine valley reserve with over 700 plant species above Ordino",
        "Sorteny Valley protects 1,080 ha of high alpine meadow above Ordino and is "
        "home to more than 700 catalogued plant species, including the endemic Vilarrasa "
        "saxifrage. A network of marked trails climbs from the valley refuge to the "
        "Estanys de l'Angonella at 2,300 m.",
    ),
    (
        "Comapedrosa Valleys Natural Park", 42.6022, 1.4592, 15, 5, 82, "1–2 days", "mountain-park",
        "Natural park around Andorra's highest summit (2,942 m)",
        "Established in 2006, Comapedrosa Valleys Natural Park covers 1,542 ha around "
        "the country's highest peak. Glacial lakes, granite ridges, and the refugi "
        "del Pla de l'Estany make it the main destination for summer hikers from Arinsal.",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(name: str, country: str = "andorra") -> str:
    raw = f"{name}-{country}".lower()
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    out: list[str] = []
    prev_dash = True
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return ("".join(out)).strip("-")[:80] or "andorra"


def bbox_from_point(lat: float, lng: float, km: float = 6.0) -> tuple[float, float, float, float]:
    import math
    dlat = km / 111.0
    dlng = km / (111.0 * max(0.35, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def open_writable(primary: Path) -> tuple[sqlite3.Connection, Path]:
    new_path = Path(f"{primary}.new")
    if new_path.exists():
        new_path.unlink()
    print(f"  copy -> {new_path.name}", flush=True)
    shutil.copyfile(primary, new_path)
    conn = sqlite3.connect(str(new_path), timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    return conn, new_path


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


# ---------------------------------------------------------------------------
# Cities
# ---------------------------------------------------------------------------


def update_cities() -> dict:
    conn, used = open_writable(CITIES_DB)
    try:
        cols = column_names(conn, "cities")
        has_category = "category" in cols
        has_locale = "locale" in cols
        added = 0
        updated = 0
        for cid, name, lat, lng, pop, tier, cat, locale in ANDORRA_CITIES:
            existing = conn.execute("SELECT id, tier, category, locale FROM cities WHERE id = ?", (cid,)).fetchone()
            if existing:
                set_parts = ["tier = ?", "name = ?", "country = ?", "cc = ?", "lat = ?", "lng = ?", "pop = ?"]
                params: list = [tier, name, "Andorra", "AD", lat, lng, pop]
                if has_category:
                    set_parts.append("category = ?")
                    params.append(cat)
                if has_locale:
                    set_parts.append("locale = ?")
                    params.append(locale)
                set_parts.append("updated_at = ?")
                params.append(NOW_ISO)
                params.append(cid)
                conn.execute(f"UPDATE cities SET {', '.join(set_parts)} WHERE id = ?", params)
                updated += 1
            else:
                base_cols = ["id", "region_id", "name", "country", "cc", "lat", "lng", "pop", "tier",
                             "source", "tagline", "activities_json", "tips_json", "photos_json",
                             "highlights_json", "enriched", "updated_at"]
                vals: list = [
                    cid, "europe", name, "Andorra", "AD", lat, lng, pop, tier,
                    "curated",
                    f"Pyrenean parish town in Andorra",
                    "[]", "[]", "[]", "[]", 0, NOW_ISO,
                ]
                if has_category:
                    base_cols.append("category")
                    vals.append(cat)
                if has_locale:
                    base_cols.append("locale")
                    vals.append(locale)
                placeholders = ", ".join(["?"] * len(vals))
                conn.execute(
                    f"INSERT INTO cities ({', '.join(base_cols)}) VALUES ({placeholders})",
                    vals,
                )
                added += 1
        conn.commit()
        return {"added": added, "updated": updated, "path": used}
    finally:
        conn.close()


def update_cities_geojson() -> dict:
    """Mirror the city changes into the source GeoJSON so rebuilds keep them."""
    if not CITIES_GEOJSON.is_file():
        return {"updated": 0, "added": 0, "path": CITIES_GEOJSON}
    data = json.loads(CITIES_GEOJSON.read_text(encoding="utf-8"))
    features = data.setdefault("features", [])
    by_id = {(f.get("properties") or {}).get("id"): f for f in features}
    added = 0
    updated = 0
    for cid, name, lat, lng, pop, tier, cat, locale in ANDORRA_CITIES:
        existing = by_id.get(cid)
        if existing:
            props = existing.setdefault("properties", {})
            if props.get("tier") != tier:
                props["tier"] = tier
                updated += 1
            props["pop"] = pop
            existing["geometry"] = {"type": "Point", "coordinates": [lng, lat]}
        else:
            features.append({
                "type": "Feature",
                "properties": {
                    "id": cid, "name": name, "country": "Andorra", "cc": "AD",
                    "pop": pop, "tier": tier,
                },
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
            })
            added += 1
    CITIES_GEOJSON.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"added": added, "updated": updated, "path": CITIES_GEOJSON}


# ---------------------------------------------------------------------------
# POIs
# ---------------------------------------------------------------------------


def tier_for_poi(popularity: int) -> str:
    if popularity >= 92:
        return "major"
    if popularity >= 78:
        return "regional"
    return "local"


def update_pois() -> dict:
    conn, used = open_writable(POI_DB)
    try:
        added = 0
        skipped = 0
        for name, lat, lng, cat, pop, tagline, summary in ANDORRA_POIS:
            pid = slugify(name)
            exists = conn.execute("SELECT 1 FROM pois WHERE id = ?", (pid,)).fetchone()
            if exists:
                skipped += 1
                continue
            west, south, east, north = bbox_from_point(lat, lng)
            tier = tier_for_poi(pop)
            conn.execute(
                """
                INSERT INTO pois (
                    id, region_id, name, country, cc, category, lat, lng,
                    popularity, tier, west, south, east, north,
                    summary, tagline, activities_json, tips_json,
                    photos_json, highlights_json, source, enriched, updated_at
                ) VALUES (?, 'europe', ?, 'Andorra', 'ad', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'curated', 0, ?)
                """,
                (
                    pid, name, cat, lat, lng, pop, tier, west, south, east, north,
                    summary[:2000], tagline[:200], "[]", "[]", "[]", "[]", NOW_ISO,
                ),
            )
            added += 1
        conn.commit()
        return {"added": added, "skipped": skipped, "path": used}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Parks
# ---------------------------------------------------------------------------


def update_parks() -> dict:
    conn, used = open_writable(PARKS_DB)
    try:
        added = 0
        skipped = 0
        cols = column_names(conn, "parks")
        has_category = "category" in cols
        for name, lat, lng, area, bio, pop, stay, cat, tagline, summary in ANDORRA_PARKS:
            pid = slugify(name)
            exists = conn.execute("SELECT 1 FROM parks WHERE id = ?", (pid,)).fetchone()
            if exists:
                skipped += 1
                continue
            # Park bboxes are larger than POI bboxes (~ area-based)
            import math
            radius_km = max(4.0, math.sqrt(max(area, 1)) * 1.5)
            west, south, east, north = bbox_from_point(lat, lng, km=radius_km)
            base_cols = [
                "id", "region_id", "name", "country", "cc", "lat", "lng",
                "area_km2", "biodiversity", "popularity", "stay",
                "west", "south", "east", "north",
                "summary", "tagline", "activities_json", "tips_json",
                "photos_json", "highlights_json", "source", "enriched", "updated_at",
            ]
            vals: list = [
                pid, "europe", name, "Andorra", "ad", lat, lng,
                area, bio, pop, stay,
                west, south, east, north,
                summary[:2000], tagline[:200],
                "[]", "[]", "[]", "[]", "curated", 0, NOW_ISO,
            ]
            if has_category:
                base_cols.append("category")
                vals.append(cat)
            placeholders = ", ".join(["?"] * len(vals))
            conn.execute(
                f"INSERT INTO parks ({', '.join(base_cols)}) VALUES ({placeholders})",
                vals,
            )
            added += 1
        conn.commit()
        return {"added": added, "skipped": skipped, "path": used}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    print("Seeding Andorra…")
    print("cities:")
    c = update_cities()
    print(f"  added={c['added']} updated={c['updated']} ({c['path'].name})")

    print("cities.geojson:")
    g = update_cities_geojson()
    print(f"  added={g['added']} updated={g['updated']} ({g['path'].name})")

    print("pois:")
    p = update_pois()
    print(f"  added={p['added']} skipped={p['skipped']} ({p['path'].name})")

    print("parks:")
    k = update_parks()
    print(f"  added={k['added']} skipped={k['skipped']} ({k['path'].name})")

    print(
        "\nNext steps:\n"
        "  python scripts/classify-places.py --apply\n"
        "  python scripts/apply-place-activities.py --apply\n"
        "  python scripts/consolidate-catalog-dbs.py\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
