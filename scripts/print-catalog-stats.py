#!/usr/bin/env python3
import sqlite3
from catalog_paths import CITIES_DB, HIKES_DB, PARKS_DB, POI_DB

for label, path, table in [
    ("cities", CITIES_DB, "cities"),
    ("hikes", HIKES_DB, "hikes"),
    ("parks", PARKS_DB, "parks"),
    ("pois", POI_DB, "pois"),
]:
    if not path.is_file():
        print(f"{label}: missing {path}")
        continue
    conn = sqlite3.connect(path)
    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    enriched = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE COALESCE(enriched,0) = 1"
    ).fetchone()[0]
    conn.close()
    print(f"{label}: {enriched}/{total} enriched")
