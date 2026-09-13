"""Richer place taxonomy used to label cards across explore catalogs.

Three independent classifiers:

* `classify_city(...)`  → (category, locale) from population, country,
                          name keywords, and proximity to curated
                          coastal/mountain/island anchors.
* `classify_park(...)`  → category from name keywords + area + coords.
* `classify_poi(...)`   → refined category from POI name keywords on
                          top of the existing broad bucket
                          (heritage / monument / fortress / mountain).

All classifiers are deterministic and rely solely on data we already
seed: `pop`, `country`, `cc`, `lat`, `lng`, `area_km2`, plus the
catalog row's own `name`. No network calls.

Card label convention (frontend):
    locale + category → "Coastal town", "Capital metropolis",
    "Mountain village", "Inland city". When locale == "inland" only the
    category label is shown.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Iterable

CITY_CATEGORIES = (
    "capital",
    "metropolis",
    "city",
    "town",
    "village",
    "hamlet",
)

CITY_LOCALES = (
    "coastal",
    "island",
    "mountain",
    "riverside",
    "inland",
)

PARK_CATEGORIES = (
    "national-park",
    "marine-park",
    "coastal-park",
    "lake-park",
    "mountain-park",
    "forest-park",
    "archaeological-park",
    "geopark",
    "nature-reserve",
)

POI_CATEGORIES = (
    "fortress",
    "palace",
    "cathedral",
    "monastery",
    "bridge",
    "archaeological",
    "mountain",
    "monument",
    "museum",
    "heritage",
    "landmark",
)


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()


# ---------------------------------------------------------------------------
# City helpers
# ---------------------------------------------------------------------------

# Capitals by country code (well-known list; ASCII normalised lower-case).
CAPITALS_BY_CC: dict[str, str] = {
    "AL": "tirana", "AD": "andorra la vella", "AT": "vienna",
    "BY": "minsk", "BE": "brussels", "BA": "sarajevo", "BG": "sofia",
    "HR": "zagreb", "CY": "nicosia", "CZ": "prague", "DK": "copenhagen",
    "EE": "tallinn", "FI": "helsinki", "FR": "paris", "DE": "berlin",
    "GR": "athens", "HU": "budapest", "IS": "reykjavik", "IE": "dublin",
    "IT": "rome", "LV": "riga", "LI": "vaduz", "LT": "vilnius",
    "LU": "luxembourg", "MT": "valletta", "MD": "chisinau", "MC": "monaco",
    "ME": "podgorica", "NL": "amsterdam", "MK": "skopje", "NO": "oslo",
    "PL": "warsaw", "PT": "lisbon", "RO": "bucharest", "RU": "moscow",
    "SM": "san marino", "RS": "belgrade", "SK": "bratislava",
    "SI": "ljubljana", "ES": "madrid", "SE": "stockholm", "CH": "bern",
    "TR": "ankara", "UA": "kyiv", "GB": "london", "VA": "vatican city",
    "XK": "pristina", "AM": "yerevan", "AZ": "baku", "GE": "tbilisi",
    "FJ": "suva", "PG": "port moresby", "SB": "honiara", "VU": "port vila",
    "NC": "noumea", "PF": "papeete", "WS": "apia", "AS": "pago pago",
    "TO": "nuku alofa", "CK": "avarua", "NU": "alofi", "PW": "melekeok",
    "GU": "hagatna", "MP": "garapan", "FM": "palikir", "MH": "majuro",
    "KI": "bairiki", "NR": "yaren", "TV": "funafuti", "WF": "mata utu",
    "NF": "kingston",
}

# Country codes that are unambiguously a single small island — every
# settlement in them is tagged `island`. Larger island/archipelago
# nations (GB, IE, IS) fall through to coastal/inland detection so
# coastal capitals stay coastal.
ISLAND_COUNTRY_CCS = {
    "MT", "CY",
    "FJ", "VU", "SB", "NC", "PF", "WS", "AS", "TO", "CK", "NU",
    "PW", "GU", "MP", "FM", "MH", "KI", "NR", "TV", "WF", "NF",
}

# Known island settlement names (lowercase, ASCII normalised) within
# continental countries. Conservative list — better to miss than mis-tag.
ISLAND_PLACE_NAMES = {
    # Croatia
    "hvar", "korcula", "brac", "supetar", "vis", "krk", "rab", "cres",
    "losinj", "mali losinj", "veli losinj", "pag", "mljet", "solta",
    # Italy
    "capri", "anacapri", "ischia", "elba", "portoferraio", "ponza",
    "lipari", "stromboli", "panarea", "salina", "favignana",
    # Greece
    "rhodes", "rhodos", "mykonos", "santorini", "thira", "naxos",
    "paros", "ios", "kos", "patmos", "samos", "lefkada", "lefkas",
    "skiathos", "skopelos", "corfu", "kerkyra", "kefalonia",
    "zakynthos", "milos", "syros", "tinos",
    # Spain
    "palma", "ibiza", "mahon", "menorca", "formentera",
    "santa cruz de tenerife", "las palmas",
    # France
    "ajaccio", "bastia", "calvi", "porto-vecchio",
    # Portugal
    "funchal", "ponta delgada",
}

# Mountain regions — settlements get the `mountain` locale when the
# country has alpine terrain AND the latitude/longitude falls inside
# one of these coarse bounding boxes.
MOUNTAIN_BOXES: list[dict] = [
    # (label, lng_min, lat_min, lng_max, lat_max)
    {"label": "alps",        "box": (5.8,  43.6, 16.5, 48.0)},
    {"label": "pyrenees",    "box": (-2.0, 42.0,  3.5, 43.4)},
    {"label": "carpathians", "box": (16.0, 45.0, 27.5, 50.5)},
    {"label": "balkans",     "box": (15.0, 41.0, 25.0, 44.5)},
    {"label": "caucasus",    "box": (38.0, 38.0, 50.0, 44.5)},
    {"label": "tatras",      "box": (19.0, 49.0, 21.5, 50.0)},
    {"label": "scottish",    "box": (-6.5, 56.0, -3.0, 58.5)},
    {"label": "scandes",     "box": ( 5.0, 60.0, 16.0, 70.0)},
]

# Curated coastal anchor points (lng, lat). A city within ~35 km of one
# is tagged `coastal`. Names are illustrative only.
COASTAL_ANCHORS: list[tuple[float, float]] = [
    # Adriatic east coast
    (13.85, 44.87), (14.44, 45.33), (15.22, 44.12), (16.44, 43.51),
    (17.13, 42.96), (18.09, 42.65), (18.77, 42.42), (19.10, 42.09),
    (19.40, 41.32), (19.45, 40.45), (19.95, 39.62),
    # Adriatic west coast
    (12.34, 45.43), (13.78, 45.65), (12.24, 44.16), (13.51, 43.62),
    (14.27, 42.36), (16.87, 41.12), (17.94, 40.64),
    # Tyrrhenian / Sicily / Sardinia
    (14.27, 40.85), (14.25, 40.83), (15.65, 38.11), (13.36, 38.12),
    (12.51, 37.79), (15.09, 37.50), (9.11,  39.22), (9.51,  40.92),
    # Aegean
    (23.73, 37.97), (22.93, 40.64), (27.13, 38.43), (25.43, 36.40),
    (28.22, 36.45), (24.95, 37.45), (27.42, 38.42),
    # Black Sea
    (28.98, 41.01), (33.83, 44.62), (39.72, 43.59), (28.58, 43.94),
    # Mediterranean — France / Spain
    (5.37,  43.30), (7.27,  43.70), (3.13,  42.50), (3.04,  41.97),
    (2.17,  41.39), (-0.38, 39.47), (-2.65, 36.84), (-3.60, 36.72),
    (-5.43, 36.14), (-6.95, 37.26), (-8.61, 37.10),
    # Atlantic west (France, Iberia)
    (-9.14, 38.72), (-8.62, 41.15), (-1.55, 47.22), (-1.66, 48.65),
    (-4.49, 48.39), (-1.10, 49.18), ( 1.85, 50.96),
    # English Channel / North Sea (mainland Europe)
    ( 0.07, 51.05), ( 4.48, 51.93), ( 4.90, 52.37),
    ( 8.81, 53.08), ( 9.99, 53.55), ( 7.06, 53.55),
    # UK & Ireland coast (Scotland north→Cornwall, plus Irish coast)
    (-3.13, 58.97), (-2.10, 57.15),   # Wick, Aberdeen
    (-3.19, 55.95),                   # Edinburgh / Firth of Forth
    (-1.40, 54.97), (-1.62, 54.50),   # Sunderland, Newcastle
    ( 0.10, 52.93),                   # Boston, Lincs
    ( 1.30, 52.62), ( 1.75, 52.49),   # Norwich, Lowestoft
    ( 1.30, 51.13),                   # Dover
    (-0.13, 50.83),                   # Brighton
    (-1.40, 50.91),                   # Portsmouth
    (-3.53, 50.72),                   # Exeter / Exmouth
    (-4.14, 50.37),                   # Plymouth
    (-5.05, 50.27),                   # Falmouth
    (-3.18, 51.48),                   # Cardiff
    (-4.04, 53.30),                   # Anglesey
    (-2.99, 53.41),                   # Liverpool
    (-2.27, 53.59),                   # Blackpool
    (-3.99, 56.46),                   # Dundee / east coast
    (-5.93, 54.60),                   # Belfast
    (-6.26, 53.35),                   # Dublin
    (-8.48, 51.90),                   # Cork
    (-9.05, 53.27),                   # Galway
    # Baltic / Scandinavia (expanded)
    (12.57, 55.68), (18.07, 59.33),
    (10.75, 59.91), ( 5.32, 60.39), (10.39, 63.43),  # Oslo, Bergen, Trondheim
    (18.96, 69.65), (14.41, 67.28),                  # Tromsø, Bodø
    (24.94, 60.17), (24.75, 59.43), (20.50, 54.71),
    (11.97, 57.71), (13.18, 55.61), (12.69, 56.05),  # Gothenburg, Malmö, Helsingborg
    (10.74, 59.91), (10.20, 56.16),                  # Aarhus DK
    # Iceland
    (-21.94, 64.13),
]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * r * math.asin(min(1, math.sqrt(a)))


def _nearest_coastal_km(lat: float, lng: float) -> float:
    best = float("inf")
    for a_lng, a_lat in COASTAL_ANCHORS:
        d = _haversine_km(lat, lng, a_lat, a_lng)
        if d < best:
            best = d
            if best < 5:
                break
    return best


COASTAL_THRESHOLD_KM = 35.0
MOUNTAIN_KEYWORDS_RE = re.compile(
    r"\b(mountain|mount|mont|alpen|alp|tatra|pic|peak|berg|hochland)\b",
    re.IGNORECASE,
)
ISLAND_KEYWORDS_RE = re.compile(r"\b(island|isle|isola|ile|otok)\b", re.IGNORECASE)


def _pop_category(pop: int | float | None, *, is_capital: bool) -> str:
    if is_capital:
        return "capital"
    p = int(pop or 0)
    if p >= 1_000_000:
        return "metropolis"
    if p >= 250_000:
        return "city"
    if p >= 40_000:
        return "town"
    if p >= 3_000:
        return "village"
    return "hamlet"


def classify_city(
    *,
    name: str,
    cc: str | None,
    pop: int | float | None,
    lat: float | None,
    lng: float | None,
) -> tuple[str, str]:
    """Return (category, locale) for a city row."""
    cc_up = (cc or "").upper()
    norm_name = _norm(name)

    is_capital = bool(
        cc_up in CAPITALS_BY_CC and CAPITALS_BY_CC[cc_up] == norm_name
    )
    category = _pop_category(pop, is_capital=is_capital)

    locale = "inland"
    if cc_up in ISLAND_COUNTRY_CCS:
        locale = "island"
    elif norm_name in ISLAND_PLACE_NAMES or ISLAND_KEYWORDS_RE.search(name or ""):
        locale = "island"
    elif lat is not None and lng is not None:
        if _nearest_coastal_km(float(lat), float(lng)) <= COASTAL_THRESHOLD_KM:
            locale = "coastal"
        else:
            if MOUNTAIN_KEYWORDS_RE.search(name or ""):
                locale = "mountain"
            else:
                for region in MOUNTAIN_BOXES:
                    lng_min, lat_min, lng_max, lat_max = region["box"]
                    if lng_min <= float(lng) <= lng_max and lat_min <= float(lat) <= lat_max:
                        locale = "mountain"
                        break
    return category, locale


# ---------------------------------------------------------------------------
# Park helpers
# ---------------------------------------------------------------------------

PARK_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("marine-park",        re.compile(r"\b(marine|sea|adriatic|aegean|atlantic|coastal park|coast park)\b", re.I)),
    ("lake-park",          re.compile(r"\b(lake|lakes|laguna|lagoon|plitvice|skadar)\b", re.I)),
    ("mountain-park",      re.compile(
        r"\b(mountain|mountains|alps|alpine|massif|highland|highlands|range|sierra|peaks|tatra|durmitor|triglav|"
        r"pyrenean|pyrenees|comapedrosa|sorteny|valley|valleys|peak|summit)\b", re.I,
    )),
    ("forest-park",        re.compile(r"\b(forest|woods|bialowieza)\b", re.I)),
    ("archaeological-park", re.compile(r"\b(archaeological|archeological|ruins|necropolis|ancient)\b", re.I)),
    ("geopark",            re.compile(r"\b(geopark|cave|caves|karst)\b", re.I)),
    ("coastal-park",       re.compile(r"\b(coast|coastline|cliff|cliffs|bay|gulf|cape|island|isles|isola|islands)\b", re.I)),
    ("nature-reserve",     re.compile(r"\b(nature reserve|biosphere|wildlife|reserve)\b", re.I)),
]

# Park categories considered hand-curated; do not demote during reclassification
# unless the new category is equally specific.
_HIGHLY_SPECIFIC_PARK_CATEGORIES = {
    "marine-park", "lake-park", "mountain-park", "forest-park",
    "archaeological-park", "geopark", "coastal-park",
}


def classify_park(
    *,
    name: str,
    area_km2: float | None,
    lat: float | None,
    lng: float | None,
    iucn_category: str | None = None,
    existing_category: str | None = None,
) -> str:
    text = name or ""
    matched: str | None = None
    for cat, pat in PARK_RULES:
        if pat.search(text):
            # Marine/coastal sanity: only tag coastal if we're actually near a coast.
            if cat in ("marine-park", "coastal-park") and lat is not None and lng is not None:
                if _nearest_coastal_km(float(lat), float(lng)) > 60:
                    continue
            matched = cat
            break

    existing = (existing_category or "").strip().lower()
    if existing in _HIGHLY_SPECIFIC_PARK_CATEGORIES:
        # Curated specific category — only override if the regex finds an
        # equally specific match different from the current one.
        if matched and matched in _HIGHLY_SPECIFIC_PARK_CATEGORIES:
            return matched
        return existing

    if matched:
        return matched

    # Fallback: nature reserve for small areas, national park otherwise.
    if area_km2 is not None and float(area_km2) < 30:
        return "nature-reserve"
    return "national-park"


# ---------------------------------------------------------------------------
# POI helpers (refine the broad bucket)
# ---------------------------------------------------------------------------

POI_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("palace",         re.compile(r"\b(palace|palazzo|imperial city|royal residence)\b", re.I)),
    ("cathedral",      re.compile(r"\b(cathedral|basilica|church|chapel|mosque|synagogue|hagia)\b", re.I)),
    ("monastery",      re.compile(r"\b(monastery|abbey|convent|shrine|stupa|lavra)\b", re.I)),
    ("bridge",         re.compile(r"\b(bridge|pont|ponte|stari most|aqueduct)\b", re.I)),
    ("archaeological", re.compile(r"\b(archaeological|archeological|ruins?|forum|amphitheatre|amphitheater|acropolis|parthenon|pompeii|herculaneum|necropolis)\b", re.I)),
    ("fortress",       re.compile(r"\b(fortress|fortifications?|fort\b|castle|citadel|kula|ramparts|city walls|defensive tower|watchtower)\b", re.I)),
    ("mountain",       re.compile(r"\b(mountain|mount|mont blanc|matterhorn|jungfrau|eiger|olympus|peak|volcano)\b", re.I)),
    ("monument",       re.compile(r"\b(monument|memorial|mausoleum|tomb|statue|column|obelisk|arch of|tower|arena|amphitheater|amphitheatre)\b", re.I)),
    ("museum",         re.compile(r"\bmuseum\b", re.I)),
]


# Categories so specific that regex must not demote them.
HIGHLY_SPECIFIC_POI_CATEGORIES = {
    "fortress",
    "palace",
    "archaeological",
    "museum",
    "mountain",
    "cathedral",
    "monastery",
    "bridge",
}


def classify_poi(*, name: str, existing_category: str | None = None) -> str:
    """Refine the POI category from the name.

    * Highly specific seed categories (fortress, palace, cathedral, …)
      are preserved verbatim so curated values are never demoted.
    * Generic seed values (monument, heritage, landmark, empty) are
      eligible for regex refinement, so e.g. `Stari Most` (seeded as
      `monument`) gets upgraded to `bridge`.
    """
    existing = (existing_category or "").lower()
    if existing in HIGHLY_SPECIFIC_POI_CATEGORIES:
        return existing

    text = name or ""
    for cat, pat in POI_RULES:
        if pat.search(text):
            return cat
    if existing in POI_CATEGORIES:
        return existing
    return "landmark"


# ---------------------------------------------------------------------------
# Labels (mirrored client-side; kept here for any server-side rendering)
# ---------------------------------------------------------------------------

CITY_CATEGORY_LABELS = {
    "capital":    "Capital",
    "metropolis": "Metropolis",
    "city":       "City",
    "town":       "Town",
    "village":    "Village",
    "hamlet":     "Hamlet",
}

CITY_LOCALE_PREFIX = {
    "coastal":   "Coastal",
    "island":    "Island",
    "mountain":  "Mountain",
    "riverside": "Riverside",
    "inland":    "",
}

PARK_CATEGORY_LABELS = {
    "national-park":      "National park",
    "marine-park":        "Marine park",
    "coastal-park":       "Coastal park",
    "lake-park":          "Lake park",
    "mountain-park":      "Mountain park",
    "forest-park":        "Forest park",
    "archaeological-park": "Archaeological park",
    "geopark":            "Geopark",
    "nature-reserve":     "Nature reserve",
}

POI_CATEGORY_LABELS = {
    "fortress":       "Fortress",
    "palace":         "Palace",
    "cathedral":      "Cathedral",
    "monastery":      "Monastery",
    "bridge":         "Bridge",
    "archaeological": "Archaeological site",
    "mountain":       "Mountain",
    "monument":       "Monument",
    "museum":         "Museum",
    "heritage":       "Heritage site",
    "landmark":       "Landmark",
}


def city_card_label(category: str, locale: str) -> str:
    prefix = CITY_LOCALE_PREFIX.get(locale, "")
    base = CITY_CATEGORY_LABELS.get(category, "City")
    if prefix:
        return f"{prefix} {base.lower()}"
    return base
