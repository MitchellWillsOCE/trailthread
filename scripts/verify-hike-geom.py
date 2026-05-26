#!/usr/bin/env python3
"""Compare hike lengths against rough expected values; surface anomalies."""
import json
import math
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "Trip" / "hikes" / "hikes.db"


def haversine_km(a, b):
    lat1, lng1 = math.radians(a[1]), math.radians(a[0])
    lat2, lng2 = math.radians(b[1]), math.radians(b[0])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def safe(t):
    return str(t).encode("ascii", "replace").decode("ascii")


# Rough expected lengths (km) for famous trails
EXPECTED = {
    "West Highland Way": 154,
    "Pennine Way": 429,
    "South West Coast Path": 1014,
    "Kerry Way": 214,
    "Wicklow Way": 130,
    "Tour du Mont Blanc": 170,
    "GR 10": 866,
    "GR 20": 180,
    "Alta Via 1": 130,
    "Alpine Pass Route": 600,
    "Walker's Haute Route": 200,
    "Kungsleden": 440,
    "Nordkalottleden": 800,
    "Slovenian Mountain Trail": 599,
    "Rota Vicentina": 450,
    "Lycian Way": 540,
    "Via Francigena": 2000,
    "Camino Francés": 780,
    "E5 European Long Distance Path": 3200,
    "Malerweg": 116,
    "Rheinsteig": 320,
    "Great Glen Way": 117,
    "John Muir Way": 215,
    "Hadrian's Wall Path": 135,
    "South Downs Way": 160,
    "Pembrokeshire Coast Path": 299,
    "Offa's Dyke Path": 285,
    "Cotswold Way": 164,
    "Beara Way": 196,
    "Pieterpad": 492,
    "GR 5": 2200,
    "GR 92": 583,
    "GR 70": 272,
    "GR 11": 800,
    "Westweg": 285,
    "Eifelsteig": 313,
    "Mullerthal Trail": 112,
    "Laugavegur": 55,
    "Bohusleden": 370,
    "Alta Via 2": 180,
    "Via degli Dei": 130,
    "Camino del Norte": 825,
    "Camino Portugués": 280,
    "E4 European Long Distance Path": 12000,
    "Goldsteig": 660,
    "Moselsteig": 365,
    "Thames Path": 296,
    "Yorkshire Wolds Way": 127,
    "Cleveland Way": 177,
    "Peddars Way and Norfolk Coast Path": 134,
    "North Downs Way": 246,
    "Speyside Way": 134,
    "Southern Upland Way": 344,
    "Rob Roy Way": 124,
    "Moray Coast Trail": 80,
    "Fife Coastal Path": 187,
    "Arran Coastal Way": 105,
    "Ayrshire Coastal Path": 161,
    "Berwickshire Coastal Path": 48,
    "Borders Abbeys Way": 109,
    "Cateran Trail": 102,
    "Cowal Way": 92,
    "East Highland Way": 130,
    "Great Trossachs Path": 48,
    "Coast to Coast Walk": 309,
    "The Ridgeway": 139,
    "Glyndŵr's Way": 217,
    "Kintyre Way": 161,
    "St Cuthbert's Way": 100,
    "A Pennine Journey": 391,
    "Annandale Way": 89,
    "Voralpenweg": 386,
    "Alpe-Adria-Trail": 750,
    "Harzer Hexenstieg": 95,
    "GR 105": 99,
    "E6 European Long Distance Path": 5200,
    "E1 European Long Distance Path": 8000,
    "Sentiero Azzurro": 12,
    "St Olavsleden": 564,
    "Camino Primitivo": 313,
    "Via Romea Germanica": 2200,
    "Lechweg": 125,
    "Berliner Höhenweg": 80,
    "Ötztal Trek": 140,
    "Adlerweg": 413,
    "England Coast Path": 4500,
    "Lake District": 50,
    "Camino Inglés": 119,
    "Bibbulmun Track": 1000,
    "GR 7": 1900,
    "Salzkammergut": 350,
}


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = list(
    conn.execute(
        "SELECT id, osm_id, name, length_km, geometry_json FROM hikes ORDER BY length_km DESC"
    )
)

print(f"Total hikes: {len(rows)}")
print()
print(f"{'name':36s} {'osm_id':>10s} {'measured':>9s} {'expected':>9s} {'%':>6s}  {'status':10s}  segments")
print("-" * 120)

low = []
high = []
ok = []
unknown = []
for r in rows:
    geom = json.loads(r["geometry_json"]) if r["geometry_json"] else {}
    if isinstance(geom, dict):
        if geom.get("type") == "MultiLineString":
            n_seg = len(geom.get("coordinates", []))
        else:
            n_seg = 1 if geom.get("coordinates") else 0
    else:
        n_seg = 0
    name = r["name"]
    measured = r["length_km"]
    expected = EXPECTED.get(name)
    if expected is None:
        status = "?"
        pct = ""
        unknown.append(r)
    else:
        ratio = measured / expected if expected else 0
        pct = f"{ratio*100:.0f}%"
        if 0.6 <= ratio <= 1.5:
            status = "OK"
            ok.append(r)
        elif ratio < 0.6:
            status = "SHORT"
            low.append((r, expected))
        else:
            status = "LONG"
            high.append((r, expected))
    print(
        f"{safe(name[:36]):36s} {r['osm_id']:>10d} {measured:>9.1f} {expected or 0:>9d} {pct:>6s}  {status:10s}  {n_seg}"
    )

print()
print(f"OK: {len(ok)}   SHORT: {len(low)}   LONG: {len(high)}   no-expected: {len(unknown)}")
print()
if low:
    print("=== SHORT (likely still missing geometry) ===")
    for r, exp in low:
        print(f"  {safe(r['name']):32s} osm={r['osm_id']:>10d}  measured={r['length_km']:>7.1f}  expected={exp:>5d}")
if high:
    print("=== LONG (relation may include extensions) ===")
    for r, exp in high:
        print(f"  {safe(r['name']):32s} osm={r['osm_id']:>10d}  measured={r['length_km']:>7.1f}  expected={exp:>5d}")
