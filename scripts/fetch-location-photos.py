"""
Fetch real, location-accurate photos for each stop.

Sources (in order):
  1. Wikimedia Commons geosearch near route coordinates
  2. Wikimedia Commons text search (place name + country)
  3. Curated Wikimedia filenames for landmark accuracy
  4. Google Places photos (optional) — set GOOGLE_PLACES_API_KEY to download
     images into Trip/media/places/<slug>/ (served locally, no key in browser)

Run: python scripts/fetch-location-photos.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import enrichment_sources as _rate_src
except ImportError:
    _rate_src = None

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "Trip" / "place-details.json"
JOURNEYS_PATH = ROOT / "Trip" / "journeys.json"
MEDIA_DIR = ROOT / "Trip" / "media" / "places"

USER_AGENT = "Trailthread/1.0 (educational trip planner; +https://github.com/)"
WIKI_API = "https://commons.wikimedia.org/w/api.php"
GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()

# lng, lat
EXTRA_COORDS: dict[str, tuple[float, float]] = {
    "Plitvice": (15.613, 44.865),
    "Ha Long": (107.1186, 20.843),
    "Hạ Long": (107.1186, 20.843),
}

# Exact Wikimedia Commons filenames (without "File:" prefix)
CURATED_FILES: dict[str, list[tuple[str, str]]] = {
    "Rome": [
        ("Colosseum in Rome, Italy - April 2007.jpg", "Colosseum, Rome"),
        ("Roman Forum-photos taken by Hans Hoffmann.jpg", "Roman Forum"),
        ("Pantheon Rome 1.jpg", "Pantheon, Rome"),
    ],
    "Kotor": [
        ("Old Town Scene - Kotor - Montenegro - 02.jpg", "Kotor old town"),
        ("Bay of Kotor from Lovćen.jpg", "Bay of Kotor"),
        ("Kotor Cathedral of Saint Tryphon.jpg", "Cathedral of Saint Tryphon, Kotor"),
    ],
    "Dubrovnik": [
        ("Dubrovnik Old Town from the city walls.jpg", "Dubrovnik old town from the walls"),
        ("Stradun, Dubrovnik, Croatia.jpg", "Stradun, Dubrovnik"),
    ],
    "Plitvice Lakes National Park": [
        ("Plitvice Lakes National Park BW 2014-10-13 13-07-14.jpg", "Plitvice Lakes waterfalls"),
        ("Plitvice Lakes, Croatia, Galovac jezero.jpg", "Galovac lake, Plitvice"),
        ("National park Plitvice lakes Croatia.jpg", "Plitvice boardwalks"),
    ],
    "Plitvice": [
        ("Plitvice Lakes National Park BW 2014-10-13 13-07-14.jpg", "Plitvice Lakes waterfalls"),
        ("Plitvice Lakes, Croatia, Galovac jezero.jpg", "Galovac lake, Plitvice"),
    ],
    "Durmitor National Park": [
        ("Crno jezero Durmitor.jpg", "Black Lake (Crno jezero), Durmitor"),
        ("National Park Durmitor from Cliff.jpg", "Durmitor peaks"),
        ("Durmitor National Park, Montenegro.jpg", "Durmitor massif"),
    ],
    "Biogradska Gora National Park": [
        ("Biogradsko Lake, Montenegro.jpg", "Biogradsko Lake"),
        ("Rainforest in the Biogradska Gora National Park.jpg", "Primeval forest, Biogradska Gora"),
        ("Biogradska gora national park.jpg", "Biogradska Gora"),
    ],
    "Lovćen National Park": [
        ("Bay of Kotor from Lovćen.jpg", "Bay of Kotor from Lovćen"),
        ("Lovćen mausoleum.jpg", "Njegoš Mausoleum, Lovćen"),
        ("Lovćen National Park, Montenegro.jpg", "Lovćen ridge"),
    ],
    "Mostar": [
        ("Stari Most Mostar.jpg", "Stari Most (Old Bridge), Mostar"),
        ("Mostar Old Town.jpg", "Mostar old town"),
    ],
    "Split": [
        ("Diocletian's Palace, Split, Croatia.jpg", "Diocletian's Palace, Split"),
        ("Riva, Split, Croatia.jpg", "Riva waterfront, Split"),
    ],
    "Bar": [
        ("Stari Bar, Montenegro.jpg", "Stari Bar ruins"),
        ("Bar, Montenegro - panoramio.jpg", "Bar harbour area"),
    ],
    "Budva Old Town": [
        ("Budva Old Town, Montenegro.jpg", "Budva old town"),
        ("Citadel in Budva, Montenegro.jpg", "Budva citadel"),
    ],
    "Old Town of Budva": [
        ("Budva Old Town, Montenegro.jpg", "Budva old town"),
    ],
    "Tokyo": [
        ("Shibuya Crossing 2018.jpg", "Shibuya Crossing, Tokyo"),
        ("Sensoji Temple Tokyo Skytree View.jpg", "Senso-ji temple, Asakusa"),
    ],
    "Kyoto": [
        ("Kinkaku-ji Golden Pavilion Kyoto.jpg", "Kinkaku-ji (Golden Pavilion)"),
        ("Fushimi Inari Taisha, Kyoto, Japan.jpg", "Fushimi Inari shrine"),
    ],
    "Granada": [
        ("Alhambra Granada Spain.jpg", "Alhambra, Granada"),
        ("Albaicín, Granada, Spain.jpg", "Albaicín quarter, Granada"),
    ],
    "Madrid": [
        ("Palacio de Cristal, Madrid, España, 2014-05-11, DD 01.jpg", "Retiro Park, Madrid"),
        ("Plaza Mayor Madrid.jpg", "Plaza Mayor, Madrid"),
    ],
    "Gergeti Trinity Church": [
        ("Gergeti Trinity Church, Georgia.jpg", "Gergeti Trinity Church with Kazbek"),
        ("Gergetier Dreifaltigkeitskirche.jpg", "Gergeti church and mountains"),
        ("Church of the Holy Trinity, Gergeti.jpg", "Holy Trinity Church, Gergeti"),
    ],
    "Bari": [
        ("Bari Vecchia aerial view.jpg", "Bari Vecchia (old town)"),
        ("Basilica di San Nicola (Bari) - Esterno.jpg", "Basilica di San Nicola, Bari"),
        ("Lungomare di Bari.jpg", "Lungomare promenade, Bari"),
    ],
    "Herceg Novi": [
        ("Herceg Novi, Montenegro.jpg", "Herceg Novi bay"),
        ("Kanli Kula, Herceg Novi.jpg", "Kanli Kula fortress"),
    ],
    "Kanli kula": [
        ("Kanli Kula, Herceg Novi.jpg", "Kanli Kula fortress"),
    ],
    "Ananuri Fortress Complex": [
        ("Ananuri fortress (Georgia).jpg", "Ananuri fortress, Georgia"),
    ],
    "Geghard": [
        ("Geghard monastery Armenia.jpg", "Geghard Monastery"),
    ],
    "Tbilisi": [
        ("Old Tbilisi, Georgia.jpg", "Old Tbilisi"),
        ("Narikala Fortress, Tbilisi.jpg", "Narikala Fortress"),
    ],
    "Ha Long": [
        ("Ha Long Bay, Vietnam.jpg", "Ha Long Bay karsts"),
        ("Halong Bay Vietnam.jpg", "Ha Long Bay cruise"),
    ],
    "Hạ Long": [
        ("Ha Long Bay, Vietnam.jpg", "Ha Long Bay karsts"),
        ("Halong Bay Vietnam.jpg", "Ha Long Bay cruise"),
    ],
    "Hanoi": [
        ("Hoan Kiem Lake, Hanoi, Vietnam.jpg", "Hoan Kiem Lake, Hanoi"),
        ("Temple of Literature, Hanoi.jpg", "Temple of Literature, Hanoi"),
    ],
    "Hoi An": [
        ("Hoi An Ancient Town, Vietnam.jpg", "Hoi An ancient town lanterns"),
    ],
    "Hue": [
        ("Imperial City, Hue, Vietnam.jpg", "Hue Imperial City"),
    ],
    "Gibraltar Old Town": [
        ("Rock of Gibraltar from the Mediterranean.jpg", "Rock of Gibraltar"),
        ("Main Street, Gibraltar.jpg", "Main Street, Gibraltar"),
    ],
    "Gibraltar": [
        ("Rock of Gibraltar from the Mediterranean.jpg", "Rock of Gibraltar"),
    ],
    "Carcassonne": [
        ("Cité de Carcassonne, France.jpg", "Cité de Carcassonne"),
    ],
    "Krka National Park": [
        ("Krka National Park Skradinski buk.jpg", "Skradinski buk waterfalls, Krka"),
    ],
    "Paklenica National Park": [
        ("Paklenica National Park canyon.jpg", "Paklenica canyon"),
    ],
}

COORD_ALIASES = {
    "Plitvice": "Plitvice Lakes National Park",
    "Ha Long": "Hạ Long",
    "Old Town of Budva": "Budva Old Town",
    "Gibraltar": "Gibraltar Old Town",
    "Ananuri": "Ananuri Fortress Complex",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[-\s]+", "-", s).strip("-")[:60]


def wiki_file_url(filename: str, width: int = 1200) -> str:
    encoded = urllib.parse.quote(filename.replace(" ", "_"))
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded}?width={width}"


def http_json(url: str, params: dict | None = None, *, retries: int = 6) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    if _rate_src is not None:
        result = _rate_src.http_get_json(full, retries=retries)
        return result if isinstance(result, dict) else {}
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            last_err = err
            if err.code in (429, 503):
                time.sleep(min(60, 4 * (attempt + 1)))
                continue
            raise
        except OSError as err:
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"HTTP failed after {retries} tries: {last_err}")


def url_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT, "Range": "bytes=0-512"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 206)
    except urllib.error.HTTPError as err:
        return err.code == 416
    except OSError:
        return False


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def place_tokens(name: str, country: str) -> set[str]:
    stop = {
        "old", "town", "national", "park", "the", "and", "of", "bay", "cave",
        "fortress", "church", "new", "upper", "link", "cruise", "complex",
    }
    words = re.findall(r"[a-z0-9]{3,}", f"{name} {country}".lower())
    return {w for w in words if w not in stop}


def is_relevant(file_title: str, caption: str, tokens: set[str]) -> bool:
    text = f"{file_title} {caption}".lower().replace("_", " ")
    if not tokens:
        return True
    for tok in sorted(tokens, key=len, reverse=True):
        if len(tok) >= 4 and tok in text:
            return True
    return False


def parse_wiki_image_pages(pages: dict) -> list[dict]:
    results = []
    for page in pages.values():
        if "imageinfo" not in page:
            continue
        info = page["imageinfo"][0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        meta = info.get("extmetadata", {})
        caption = ""
        for key in ("ObjectName", "ImageDescription"):
            if key in meta:
                caption = strip_html(meta[key].get("value", ""))
                if caption:
                    break
        title = page.get("title", "").replace("File:", "")
        results.append(
            {
                "url": url,
                "caption": caption or title,
                "source": "Wikimedia Commons",
            }
        )
    return results


def wiki_batch_files(file_titles: list[str]) -> list[dict]:
    if not file_titles:
        return []
    data = http_json(
        WIKI_API,
        {
            "action": "query",
            "titles": "|".join(file_titles[:40]),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": 1200,
            "format": "json",
        },
    )
    return parse_wiki_image_pages(data.get("query", {}).get("pages", {}))


def wiki_geosearch(lat: float, lng: float, radius_m: int = 2500, limit: int = 6) -> list[dict]:
    data = http_json(
        WIKI_API,
        {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lng}",
            "gsradius": radius_m,
            "gsrlimit": limit,
            "gsnamespace": 6,
            "format": "json",
        },
    )
    titles = [
        item["title"]
        for item in data.get("query", {}).get("geosearch", [])
        if item.get("title", "").startswith("File:")
    ]
    time.sleep(0.8)
    return wiki_batch_files(titles)


def wiki_text_search(query: str, limit: int = 8) -> list[dict]:
    data = http_json(
        WIKI_API,
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": 1200,
            "format": "json",
        },
    )
    return parse_wiki_image_pages(data.get("query", {}).get("pages", {}))


def google_place_photos(name: str, country: str, lng: float | None, lat: float | None, slug: str, max_count: int = 4) -> list[dict]:
    if not GOOGLE_KEY:
        return []

    query = f"{name}, {country}" if country else name
    params: dict = {
        "input": query,
        "inputtype": "textquery",
        "fields": "place_id,name,photos",
        "key": GOOGLE_KEY,
    }
    if lat is not None and lng is not None:
        params["locationbias"] = f"circle:8000@{lat},{lng}"

    data = http_json("https://maps.googleapis.com/maps/api/place/findplacefromtext/json", params)
    candidates = data.get("candidates", [])
    if not candidates:
        return []

    place = candidates[0]
    photos = place.get("photos", [])[:max_count]
    out_dir = MEDIA_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, photo in enumerate(photos):
        ref = photo.get("photo_reference")
        if not ref:
            continue
        photo_url = (
            "https://maps.googleapis.com/maps/api/place/photo"
            f"?maxwidth=1200&photo_reference={urllib.parse.quote(ref)}&key={GOOGLE_KEY}"
        )
        local_name = f"{i + 1}.jpg"
        local_path = out_dir / local_name
        try:
            req = urllib.request.Request(photo_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                local_path.write_bytes(resp.read())
            rel = f"./Trip/media/places/{slug}/{local_name}"
            place_name = place.get("name", name)
            results.append(
                {
                    "url": rel,
                    "caption": f"{place_name} — photo via Google Maps",
                    "source": "Google Maps",
                }
            )
        except OSError as err:
            log(f"  google download failed {name}: {err}")
        time.sleep(0.2)
    return results


def load_route_coords() -> dict[str, tuple[float, float]]:
    coords: dict[str, tuple[float, float]] = {}
    for path in ROOT.glob("Trip/**/*.geojson"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for feature in data.get("features", []):
            if feature.get("geometry", {}).get("type") != "Point":
                continue
            name = feature.get("properties", {}).get("name")
            if not name:
                continue
            lng, lat = feature["geometry"]["coordinates"][:2]
            coords[name] = (lng, lat)
    coords.update(EXTRA_COORDS)
    for alias, target in COORD_ALIASES.items():
        if target in coords and alias not in coords:
            coords[alias] = coords[target]
    return coords


def collect_photos(name: str, country: str, lng: float | None, lat: float | None) -> list[dict]:
    tokens = place_tokens(name, country)
    seen: set[str] = set()
    photos: list[dict] = []

    def add(entry: dict | None, *, require_relevance: bool = True, file_hint: str = "") -> None:
        if not entry:
            return
        url = entry.get("url", "")
        if not url or url in seen:
            return
        caption = entry.get("caption", name)
        hint = file_hint or caption
        if require_relevance and not is_relevant(hint, caption, tokens):
            return
        seen.add(url)
        item = {"url": url, "caption": f"{caption} — {name}" if name.lower() not in caption.lower() else caption}
        if entry.get("source"):
            item["source"] = entry["source"]
        photos.append(item)

    for filename, caption in CURATED_FILES.get(name, []):
        url = wiki_file_url(filename)
        add({"url": url, "caption": caption, "source": "Wikimedia Commons"}, require_relevance=False)
        time.sleep(0.35)

    if lat is not None and lng is not None and len(photos) < 6:
        for entry in wiki_geosearch(lat, lng):
            add(entry, require_relevance=True, file_hint=entry.get("caption", ""))
            if len(photos) >= 6:
                break

    if len(photos) < 4:
        search_query = f"{name} {country}".strip()
        for entry in wiki_text_search(search_query, limit=8):
            add(entry, file_hint=entry.get("caption", ""))
            if len(photos) >= 6:
                break
        time.sleep(1.0)

    slug = slugify(name)
    for entry in google_place_photos(name, country, lng, lat, slug):
        add(entry, require_relevance=False)
        if len(photos) >= 6:
            break

    return photos[:6]


def collect_trail_photos(
    name: str,
    country: str,
    lng: float | None,
    lat: float | None,
    *,
    limit: int = 5,
) -> list[dict]:
    """Wikimedia Commons images along a trail (geosearch + trail-themed text search)."""
    seen: set[str] = set()
    photos: list[dict] = []

    def push(entry: dict) -> None:
        url = entry.get("url", "")
        if not url or url in seen:
            return
        seen.add(url)
        cap = entry.get("caption") or name
        item = {"url": url, "caption": cap, "source": entry.get("source") or "Wikimedia Commons"}
        photos.append(item)

    if lat is not None and lng is not None:
        for entry in wiki_geosearch(lat, lng, radius_m=15000, limit=10):
            push(entry)
            if len(photos) >= limit:
                return photos[:limit]
            time.sleep(0.25)

    queries = [
        f"{name} hiking {country}",
        f"{name} trail {country}",
        f"{name} footpath mountains",
        f"{name} {country}",
    ]
    for q in queries:
        if len(photos) >= limit:
            break
        for entry in wiki_text_search(q, limit=8):
            push(entry)
            if len(photos) >= limit:
                return photos[:limit]
        time.sleep(0.85)

    return photos[:limit]


def build_trip_gallery(trip: dict, place_names: list[str], all_photos: dict[str, list]) -> list[dict]:
    gallery = []
    seen: set[str] = set()

    def push(entry: dict) -> None:
        url = entry.get("url")
        if url and url not in seen:
            seen.add(url)
            gallery.append({"url": url, "caption": entry.get("caption", trip.get("title", ""))})

    for key in (trip.get("key", ""),):
        for filename, caption in CURATED_FILES.get(trip.get("title", ""), []):
            push({"url": wiki_file_url(filename), "caption": caption})

    if trip.get("cover"):
        push({"url": trip["cover"], "caption": trip.get("title", "")})

    for name in place_names[:6]:
        for entry in all_photos.get(name, [])[:2]:
            push(entry)
        if len(gallery) >= 6:
            break
    return gallery[:6]


def log(msg: str) -> None:
    text = str(msg).encode("ascii", errors="replace").decode("ascii")
    print(text, flush=True)


def needs_refresh(entry: dict) -> bool:
    photos = entry.get("photos") or []
    if not photos:
        return True
    for photo in photos:
        url = photo.get("url", photo) if isinstance(photo, dict) else photo
        if "unsplash.com" in str(url):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Refresh every place (default: only stale Unsplash entries)")
    args = parser.parse_args()

    coords = load_route_coords()
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    updated = 0

    for name, entry in sorted(data.items()):
        if not args.all and not needs_refresh(entry):
            continue
        country = entry.get("country", "")
        lng, lat = coords.get(name, (None, None))
        log(f"Fetching: {name} ({country})...")
        photos = collect_photos(name, country, lng, lat)
        if photos:
            entry["photos"] = photos
            updated += 1
            log(f"  -> {len(photos)} photos")
        else:
            log("  -> no photos found, keeping existing")
        DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        time.sleep(1.2)

    log("\nPlace details saved.")

    journeys = json.loads(JOURNEYS_PATH.read_text(encoding="utf-8"))
    trip_stops: dict[str, list[str]] = {}
    for path in ROOT.glob("Trip/**/*.geojson"):
        manifest_key = None
        for trip in journeys.get("trips", []):
            if trip.get("geojson", "").replace("\\", "/").endswith(path.name):
                manifest_key = trip["key"]
                break
        if not manifest_key:
            continue
        stops = []
        geo = json.loads(path.read_text(encoding="utf-8"))
        for f in geo.get("features", []):
            if f.get("geometry", {}).get("type") == "Point":
                n = f.get("properties", {}).get("name")
                if n:
                    stops.append(n)
        trip_stops[manifest_key] = stops

    for trip in journeys.get("trips", []):
        stops = trip_stops.get(trip["key"], [])
        gallery = build_trip_gallery(trip, stops, {n: data[n]["photos"] for n in stops if n in data and data[n].get("photos")})
        if gallery:
            trip["gallery"] = gallery
            trip["cover"] = gallery[0]["url"]

    JOURNEYS_PATH.write_text(json.dumps(journeys, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"\nUpdated {updated} places. Google API: {'yes' if GOOGLE_KEY else 'no (Wikimedia only)'}")
    log(f"Data: {DATA_PATH}")


if __name__ == "__main__":
    main()
