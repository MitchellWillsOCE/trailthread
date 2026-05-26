"""Re-derive `stopType` (and matching `section`) for every journey stop.

Why: many route GeoJSONs label churches, fortresses, etc. as `park`
(green), or label parks/POIs as cities. This walks every route file
under Trip/ and the shared-journeys store, infers the correct
`stopType` from name patterns + the curated catalogs (cities.db,
parks.db, poi.db), and rewrites entries where they disagree.

Rules (priority order, first match wins):
  1. `start` / `end` are preserved (they are positional markers).
  2. Explicit name → kind overrides (curated dict below).
  3. Park-name regex (National Park, Nature Park, Biosphere Reserve, …).
  4. Heritage-name regex (Cathedral, Church, Monastery, Mosque, Temple,
     Palace, Castle, Fortress, Citadel, Tower, Old Town, Imperial City,
     Walls, Bridge, Abbey, Basilica, Acropolis, Arena, …).
  5. Famous-mountain regex (Mount, Mt., Peak, Volcano) → heritage POI.
  6. Nature-feature regex (Cave, Bay, Lake, Island, Beach, Gorge, Falls,
     River) → park.
  7. POI catalog hit → heritage.
  8. Parks catalog hit → park.
  9. Cities catalog hit → city.
 10. Fallback: keep the existing value if valid, else `city`.

Run `python scripts/fix-stop-types.py` to preview. Pass `--apply` to
write the changes. The script does surgical text replacement so
file formatting (single-line vs pretty) is preserved.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from catalog_paths import CITIES_DB, PARKS_DB, POI_DB  # noqa: E402

TRIP_DIR = ROOT / "Trip"
SHARED_DIR = TRIP_DIR / "shared-journeys"

VALID_STOP_TYPES = {"start", "end", "city", "park", "heritage"}
SECTION_BY_STOP = {"city": "cities", "park": "parks", "heritage": "heritage"}


def normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return text


PARK_NAME_RE = re.compile(
    r"\b(national park|nature park|national reserve|national lakes|"
    r"biosphere reserve|geopark|wildlife reserve|nature reserve|"
    r"protected area)\b",
    re.IGNORECASE,
)

HERITAGE_NAME_RE = re.compile(
    r"\b("
    r"cathedral|basilica|church|chapel|abbey|monastery|convent|mosque|"
    r"synagogue|temple|shrine|sanctuary|"
    r"castle|fortress|fortifications?|citadel|kula|tower|wall(s)?|fort|"
    r"palace|palazzo|imperial city|old town|old district|old bazaar|"
    r"historic centre|historic center|historic quarter|archaeological|"
    r"acropolis|amphitheatre|amphitheater|arena|forum|"
    r"bridge|aqueduct|baths?|hammam|"
    r"sea organ|pyramid|necropolis|catacombs|"
    r"monument|memorial|mausoleum|tomb"
    r")\b",
    re.IGNORECASE,
)

MOUNTAIN_NAME_RE = re.compile(
    r"\b(mount|mt\.?|peak|summit|volcano|matterhorn|jungfrau|eiger|"
    r"mont blanc|grossglockner|olympus)\b",
    re.IGNORECASE,
)

NATURE_NAME_RE = re.compile(
    r"\b(cave|caves|grotto|bay|lagoon|fjord|lake|lakes|island|islands|"
    r"isle|beach|coast|gorge|canyon|falls|waterfall|river|delta|"
    r"plateau|valley|meadow|forest|woods|dunes|crater)\b",
    re.IGNORECASE,
)

EXPLICIT_OVERRIDES: dict[str, str] = {
    "gergeti trinity church": "heritage",
    "the marble mountains": "heritage",
    "marble mountains": "heritage",
    "bellegarde fort": "heritage",
    "gibraltar old town": "heritage",
    "rock of gibraltar": "park",
    "kanazawa old district": "heritage",
    "kenroku-en": "park",
    "azhdahak": "park",
    "kanli kula": "heritage",
    "blue cave": "park",
    "badanj cave": "park",
    "ha long": "park",
    "hạ long": "park",
    "ha long bay": "park",
    "hạ long bay": "park",
    "phong nha - ke bang national park": "park",
    "hue imperial city": "heritage",
    "st. joseph cathedral": "heritage",
    "ananuri fortress complex": "heritage",
    "geghard": "heritage",
}


def load_catalog_names(db_path: Path, table: str) -> set[str]:
    if not db_path.is_file():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"SELECT name FROM {table}").fetchall()
    finally:
        conn.close()
    return {normalize(r[0]) for r in rows if r[0]}


CITIES = load_catalog_names(CITIES_DB, "cities")
PARKS = load_catalog_names(PARKS_DB, "parks")
POIS = load_catalog_names(POI_DB, "pois")


def infer_stop_type(name: str, current: str, *, kind: str = "") -> str:
    if current in ("start", "end"):
        return current

    key = normalize(name)
    if not key:
        return current if current in VALID_STOP_TYPES else "city"

    if key in EXPLICIT_OVERRIDES:
        return EXPLICIT_OVERRIDES[key]

    if PARK_NAME_RE.search(name):
        return "park"
    if HERITAGE_NAME_RE.search(name):
        return "heritage"
    if MOUNTAIN_NAME_RE.search(name):
        return "heritage"
    if NATURE_NAME_RE.search(name):
        return "park"

    if key in POIS:
        return "heritage"
    if key in PARKS:
        return "park"
    if key in CITIES:
        return "city"

    k = (kind or "").lower()
    if k == "poi":
        return "heritage"
    if k == "park":
        return "park"
    if k == "city":
        return "city"

    return current if current in VALID_STOP_TYPES else "city"


def patch_kv(
    text: str,
    feature_start: int,
    feature_end: int,
    key: str,
    new_value: str,
) -> tuple[str, bool]:
    """Replace `"<key>": "..."` inside [feature_start, feature_end)."""
    window = text[feature_start:feature_end]
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"')
    m = pattern.search(window)
    if not m or m.group(1) == new_value:
        return text, False
    replacement = f'"{key}": "{new_value}"'
    new_window = window[: m.start()] + replacement + window[m.end():]
    return text[:feature_start] + new_window + text[feature_end:], True


def find_feature_blocks(text: str) -> list[tuple[int, int]]:
    """Return [(start, end)] of every top-level object inside `"features": [ ... ]`.

    Walks the array character-by-character with brace balancing so it
    works for both compact (one feature per line) and pretty-printed
    files.
    """
    m = re.search(r'"features"\s*:\s*\[', text)
    if not m:
        return []
    blocks: list[tuple[int, int]] = []
    depth = 0
    obj_start = -1
    in_str = False
    escape = False
    i = m.end()
    while i < len(text):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                if depth == 0:
                    obj_start = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    blocks.append((obj_start, i + 1))
                    obj_start = -1
            elif c == "]" and depth == 0:
                break
        i += 1
    return blocks


def process_route_geojson(path: Path, apply: bool) -> tuple[list[str], bool]:
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"  skip (bad JSON): {exc}"], False

    text = raw
    diffs: list[str] = []
    changed = False

    features = data.get("features", []) or []
    blocks = find_feature_blocks(text)
    if len(blocks) != len(features):
        return [
            f"  skip (could not align {len(blocks)} text blocks "
            f"with {len(features)} parsed features)"
        ], False

    # Walk features in reverse so earlier offsets stay valid as we
    # rewrite later blocks.
    for idx in range(len(features) - 1, -1, -1):
        feat = features[idx]
        if (feat.get("geometry") or {}).get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        name = props.get("name") or ""
        if not name:
            continue
        current_stop = props.get("stopType") or "city"
        current_section = props.get("section") or ""

        new_stop = infer_stop_type(name, current_stop)
        new_section = (
            SECTION_BY_STOP.get(new_stop, current_section)
            if new_stop not in ("start", "end")
            else current_section
        )

        stop_changed = new_stop != current_stop
        section_changed = (
            new_stop not in ("start", "end")
            and new_section != current_section
            and current_section in ("cities", "parks", "heritage", "")
        )
        if not (stop_changed or section_changed):
            continue

        f_start, f_end = blocks[idx]

        local_diffs = []
        if stop_changed:
            local_diffs.append(f"stopType {current_stop} -> {new_stop}")
        if section_changed:
            local_diffs.append(f"section {current_section} -> {new_section}")
        diffs.append(f"  - {name}: " + "; ".join(local_diffs))

        if not apply:
            continue

        if stop_changed:
            text, ok = patch_kv(text, f_start, f_end, "stopType", new_stop)
            if ok:
                changed = True
                # Refresh block end since length may have changed.
                delta = (len(new_stop) - len(current_stop))
                f_end += delta
        if section_changed:
            text, ok = patch_kv(text, f_start, f_end, "section", new_section)
            if ok:
                changed = True

    if apply and changed:
        path.write_text(text, encoding="utf-8")
    # Reverse the diffs so output reads top-to-bottom.
    diffs.reverse()
    return diffs, changed


def process_shared_journey(path: Path, apply: bool) -> tuple[list[str], bool]:
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"  skip (bad JSON): {exc}"], False

    diffs: list[str] = []
    changed = False
    stops = data.get("stops") or []
    for stop in stops:
        name = stop.get("name") or ""
        if not name:
            continue
        current = stop.get("stopType") or "city"
        kind = stop.get("kind") or ""
        new_stop = infer_stop_type(name, current, kind=kind)
        if new_stop != current:
            diffs.append(f"  - {name}: stopType {current} -> {new_stop}")
            if apply:
                stop["stopType"] = new_stop
                changed = True

    if apply and changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return diffs, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args()

    route_files = sorted(TRIP_DIR.glob("*/*-route.geojson"))
    shared_files = sorted(SHARED_DIR.glob("*.json")) if SHARED_DIR.is_dir() else []

    total_changed = 0
    for path in route_files:
        diffs, changed = process_route_geojson(path, args.apply)
        if diffs:
            print(f"\n{path.relative_to(ROOT)}")
            for line in diffs:
                print(line)
        if changed:
            total_changed += 1

    for path in shared_files:
        diffs, changed = process_shared_journey(path, args.apply)
        if diffs:
            print(f"\n{path.relative_to(ROOT)}")
            for line in diffs:
                print(line)
        if changed:
            total_changed += 1

    mode = "applied" if args.apply else "preview"
    print(f"\n[{mode}] {total_changed} file(s) with changes.")
    if not args.apply:
        print("Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
