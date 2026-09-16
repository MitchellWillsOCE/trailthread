#!/usr/bin/env python3
"""Replace demo journeys with typical first-timer trips across several countries."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIP_ROOT = ROOT / "Trip"
JOURNEYS = TRIP_ROOT / "journeys.json"
PLACE_DETAILS = TRIP_ROOT / "place-details.json"

OLD_FOLDERS = [
    "rome-bar-north-classic",
    "montenegro-heritage-arc",
    "parks-and-islands-explorer",
    "caucasus-highlands-expedition",
    "vietnam-heritage-nature-route",
    "iberia-fortresses-old-cities",
    "japan-cultural-arc",
    "japan-golden-route",
    "thailand-north",
]


def commons(name: str, width: int = 1200) -> str:
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width={width}"


def photo(name: str, caption: str) -> dict:
    return {"url": commons(name), "caption": caption, "source": "Wikimedia Commons"}


def feature_line(name: str, mode: str, day: str, coords: list[list[float]], section: str = "core") -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name, "mode": mode, "day": day, "section": section},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def feature_point(name: str, country: str, stop_type: str, day: str, lng: float, lat: float, section: str = "cities") -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name, "country": country, "stopType": stop_type, "day": day, "section": section},
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
    }


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def itinerary(title: str, days: int, distance: str, season: str, budget: str, theme: str, rows: list[tuple], modules: str) -> str:
    table = "\n".join(
        f"| {day} | {base} | {summary} | {cost} |"
        for day, base, summary, cost in rows
    )
    return f"""# {title} ({days} Days)

## Overview & Cost Estimate

**Trip Duration:** {days} days | **Distance:** {distance}
**Best Season:** {season}
**Projected Budget (per person):** {budget}

## Theme
{theme}

## Daily Itinerary

| Day | Base | Activity Summary | Cost Range |
|---|---|---|---|
{table}

## Typical add-ons
{modules}
"""


TRIPS = []


def add_trip(spec: dict) -> None:
    TRIPS.append(spec)


# --- Oceania ---
add_trip({
    "key": "eastCoastAustralia",
    "emoji": "🦘",
    "continent": "oceania",
    "folder": "east-coast-australia",
    "title": "East Coast Australia",
    "description": "The usual first Australia circuit: Sydney harbour, Blue Mountains, Canberra, Melbourne, and the Great Ocean Road.",
    "builderNote": "A typical east-coast fly-drive. Recreate it in the builder with your own nights and side trips.",
    "days": 12,
    "distanceKm": 1680,
    "budgetAudMin": 3800,
    "budgetAudMax": 5600,
    "region": "New South Wales · ACT · Victoria",
    "cover": commons("Sydney_Harbour_Bridge_from_Circular_Quay.jpg"),
    "highlights": [
        "Harbour ferries and the Bondi-to-Coogee walk",
        "Three Sisters and Jamison Valley lookouts",
        "Great Ocean Road from Torquay toward the Twelve Apostles",
    ],
    "gallery_files": [
        ("Sydney_Harbour_Bridge_from_Circular_Quay.jpg", "Sydney Harbour from Circular Quay"),
        ("Commercial_buildings_top_of_Katoomba_Street.jpg", "Katoomba, Blue Mountains"),
        ("Canberra_from_Mount_Ainslie.jpg", "Canberra from Mount Ainslie"),
        ("Flinders_Street_Station_Melbourne_2010.jpg", "Flinders Street Station, Melbourne"),
        ("Twelve_Apostles%2C_Victoria%2C_Australia.jpg", "Twelve Apostles, Great Ocean Road"),
    ],
    "points": [
        ("Sydney", "Australia", "start", "1", 151.2093, -33.8688),
        ("Katoomba", "Australia", "park", "4", 150.3119, -33.7128),
        ("Canberra", "Australia", "city", "6", 149.13, -35.2809),
        ("Melbourne", "Australia", "city", "8", 144.9631, -37.8136),
        ("Torquay", "Australia", "end", "11", 144.317, -38.333),
    ],
    "lines": [
        ("Sydney to Katoomba", "train", "4", [[151.2093, -33.8688], [150.3119, -33.7128]]),
        ("Katoomba to Canberra", "drive", "6", [[150.3119, -33.7128], [149.13, -35.2809]]),
        ("Canberra to Melbourne", "fly", "8", [[149.13, -35.2809], [147.0, -36.6], [144.9631, -37.8136]]),
        ("Melbourne to Torquay", "drive", "11", [[144.9631, -37.8136], [144.317, -38.333]]),
    ],
    "itinerary": itinerary(
        "East Coast Australia", 12, "~1,680 km",
        "March–May, September–November",
        "AUD 3,800–5,600",
        "Harbour city, sandstone mountains, the capital, laneway Melbourne, and a Great Ocean Road finish — the trip most first-time visitors actually book.",
        [
            ("1–3", "Sydney", "Opera House and The Rocks, ferry to Manly, Bondi to Coogee coastal walk", "AUD 140–200"),
            ("4–5", "Katoomba", "Train into the Blue Mountains; Three Sisters, Scenic World or a cliff walk", "AUD 120–170"),
            ("6–7", "Canberra", "Drive or coach via the highlands; Parliament, War Memorial, Lake Burley Griffin", "AUD 110–160"),
            ("8–10", "Melbourne", "Short flight; laneways, tram loop, day on the peninsula or in the Yarra Valley", "AUD 140–200"),
            ("11–12", "Torquay", "Great Ocean Road toward Lorne and the Twelve Apostles; return to Melbourne to fly out", "AUD 130–190"),
        ],
        "- Add Byron Bay or the Gold Coast before Sydney if you have 16+ days.\n- Winter (Jun–Aug) is fine in the south but colder in the mountains.",
    ),
})

add_trip({
    "key": "southIslandNz",
    "emoji": "🏔️",
    "continent": "oceania",
    "folder": "south-island-new-zealand",
    "title": "South Island New Zealand",
    "description": "The classic South Island loop: Christchurch to Queenstown, a Fiordland day, then Wanaka on the return.",
    "builderNote": "Typical camper or fly-drive routing. Swap Te Anau for Milford if you book the coach-cruise.",
    "days": 10,
    "distanceKm": 980,
    "budgetAudMin": 3200,
    "budgetAudMax": 4900,
    "region": "Canterbury · Otago · Fiordland",
    "cover": commons("Queenstown_New_Zealand.jpg"),
    "highlights": [
        "Christchurch restart and the inland alpine drive",
        "Queenstown as the adventure and lake base",
        "Te Anau or Milford Sound day, then Wanaka",
    ],
    "gallery_files": [
        ("Queenstown_New_Zealand.jpg", "Queenstown, Lake Wakatipu"),
        ("Christchurch_from_the_Port_Hills.jpg", "Christchurch from the Port Hills"),
        ("Milford_Sound%2C_New_Zealand.jpg", "Milford Sound"),
        ("Lake_Wanaka.jpg", "Lake Wānaka"),
        ("Aoraki_Mount_Cook.jpg", "Aoraki / Mount Cook"),
    ],
    "points": [
        ("Christchurch", "New Zealand", "start", "1", 172.6362, -43.5321),
        ("Queenstown", "New Zealand", "city", "3", 168.6626, -45.0312),
        ("Te Anau", "New Zealand", "park", "6", 167.718, -45.416),
        ("Wanaka", "New Zealand", "end", "8", 169.1321, -44.7032),
    ],
    "lines": [
        ("Christchurch to Queenstown", "drive", "3", [[172.6362, -43.5321], [170.5, -44.2], [168.6626, -45.0312]]),
        ("Queenstown to Te Anau", "drive", "6", [[168.6626, -45.0312], [167.718, -45.416]]),
        ("Te Anau to Wanaka", "drive", "8", [[167.718, -45.416], [168.7, -44.9], [169.1321, -44.7032]]),
    ],
    "itinerary": itinerary(
        "South Island New Zealand", 10, "~980 km",
        "November–April (shoulder: March, November)",
        "AUD 3,200–4,900",
        "The South Island circuit most visitors drive: garden city start, lakes and adventure at Queenstown, a Fiordland day, then quieter Wanaka.",
        [
            ("1–2", "Christchurch", "Rebuild precincts, Botanic Gardens, Port Hills lookout; collect a car", "AUD 110–160"),
            ("3–5", "Queenstown", "Inland alpine drive via Tekapo or Lindis; lake, gondola, optional shotover or vineyard", "AUD 160–230"),
            ("6–7", "Te Anau", "Gateway to Fiordland; Milford or Doubtful Sound day cruise", "AUD 180–280"),
            ("8–9", "Wanaka", "Lake walk, Roy's Peak or a quieter lake day; return via Hawea", "AUD 130–190"),
            ("10", "Christchurch or Queenstown", "Drive back to Christchurch or fly out of Queenstown", "AUD 80–220"),
        ],
        "- Book Milford weather windows and huts early in summer.\n- Winter is beautiful but alpine roads need planning.",
    ),
})

add_trip({
    "key": "fijiIslands",
    "emoji": "🌴",
    "continent": "oceania",
    "folder": "fiji-islands",
    "title": "Fiji Islands",
    "description": "A typical first Fiji stay: Nadi as the gateway, Pacific Harbour for reefs and rivers, then Suva for the capital and markets.",
    "builderNote": "Swap Pacific Harbour for a Mamanuca island if you want a resort week instead of a land circuit.",
    "days": 8,
    "distanceKm": 220,
    "budgetAudMin": 2400,
    "budgetAudMax": 3900,
    "region": "Viti Levu · Fiji",
    "cover": commons("Fiji_from_the_air.jpg"),
    "highlights": [
        "Nadi temples and Denarau transfers",
        "Pacific Harbour diving, rivers, and Beqa lagoon",
        "Suva museum, market, and Colo-i-Suva forest",
    ],
    "gallery_files": [
        ("Sri_Siva_Subramaniya_Temple.jpg", "Sri Siva Subramaniya Temple, Nadi"),
        ("Suva_Fiji.jpg", "Suva harbour"),
        ("Colo-i-Suva_Forest_Park.jpg", "Colo-i-Suva Forest Park"),
        ("Beqa_Lagoon.jpg", "Beqa Lagoon"),
        ("Nadi_airport_Fiji.jpg", "Nadi gateway"),
    ],
    "points": [
        ("Nadi", "Fiji", "start", "1", 177.4356, -17.7765),
        ("Pacific Harbour", "Fiji", "city", "4", 178.074, -18.241),
        ("Suva", "Fiji", "end", "6", 178.4419, -18.1416),
    ],
    "lines": [
        ("Nadi to Pacific Harbour", "drive", "4", [[177.4356, -17.7765], [178.074, -18.241]]),
        ("Pacific Harbour to Suva", "drive", "6", [[178.074, -18.241], [178.4419, -18.1416]]),
    ],
    "itinerary": itinerary(
        "Fiji Islands", 8, "~220 km on Viti Levu",
        "May–October (drier)",
        "AUD 2,400–3,900",
        "The land-based first trip: west-coast arrival, a south-coast adventure base, then a couple of nights in the capital before flying home.",
        [
            ("1–3", "Nadi", "Temple, Denarau, optional Mamanuca day boat; recover from the long-haul", "AUD 150–240"),
            ("4–5", "Pacific Harbour", "Coral Coast drive; river, shark dive or Beqa snorkel, arts village", "AUD 180–280"),
            ("6–7", "Suva", "Museum, Thurston Gardens, municipal market, Colo-i-Suva walk", "AUD 120–180"),
            ("8", "Nadi", "Return along the Queen's Road for the evening flight", "AUD 70–120"),
        ],
        "- Many visitors skip Suva and stay on one island; this route is for people who want more than a resort week.\n- Sunday is quiet in towns and villages.",
    ),
})

# --- Europe ---
add_trip({
    "key": "italyClassics",
    "emoji": "🇮🇹",
    "continent": "europe",
    "folder": "italy-classics",
    "title": "Italy Classics",
    "description": "The standard first Italy: Rome, Florence, and Venice on the high-speed train, with a Tuscan day in the middle.",
    "builderNote": "The classic rail triangle. Add the Amalfi Coast or Cinque Terre if you have 14 days.",
    "days": 10,
    "distanceKm": 720,
    "budgetAudMin": 3400,
    "budgetAudMax": 5200,
    "region": "Lazio · Tuscany · Veneto",
    "cover": commons("Colosseum_in_Rome%2C_Italy_-_April_2007.jpg"),
    "highlights": [
        "Rome's historic core and a Vatican morning",
        "Florence Duomo, Uffizi, and a Chianti or Pisa day",
        "Venice vaporetto, San Marco, and a quiet sestiere",
    ],
    "gallery_files": [
        ("Colosseum_in_Rome%2C_Italy_-_April_2007.jpg", "Colosseum, Rome"),
        ("Florence_Duomo_from_Michelangelo_hill.jpg", "Florence Duomo"),
        ("Canal_Grande_Chiesa_della_Salute_e_Dogana_dal_ponte_dell_Accademia.jpg", "Grand Canal, Venice"),
        ("Pantheon_Rome_1.jpg", "Pantheon, Rome"),
        ("Ponte_Vecchio_Firenze.jpg", "Ponte Vecchio, Florence"),
    ],
    "points": [
        ("Rome", "Italy", "start", "1", 12.4964, 41.9028),
        ("Florence", "Italy", "city", "5", 11.2558, 43.7696),
        ("Venice", "Italy", "end", "8", 12.3155, 45.4408),
    ],
    "lines": [
        ("Rome to Florence", "train", "5", [[12.4964, 41.9028], [11.2558, 43.7696]]),
        ("Florence to Venice", "train", "8", [[11.2558, 43.7696], [12.3155, 45.4408]]),
    ],
    "itinerary": itinerary(
        "Italy Classics", 10, "~720 km by Frecciarossa",
        "April–June, September–October",
        "AUD 3,400–5,200",
        "Rome–Florence–Venice is still the trip most first-time visitors take: walkable historic cores linked by 90-minute trains.",
        [
            ("1–4", "Rome", "Colosseum and Forum, Trastevere evening, Vatican or Appian day, neighbourhood walk", "AUD 150–220"),
            ("5–7", "Florence", "Morning Frecciarossa; Duomo, Uffizi or Accademia, sunset at Piazzale Michelangelo; Chianti or Pisa day", "AUD 140–210"),
            ("8–10", "Venice", "Train via Bologna; vaporetto pass, San Marco off-peak, wander Cannaregio or Giudecca", "AUD 160–240"),
        ],
        "- Book Vatican and Uffizi slots ahead in spring and autumn.\n- Add Naples/Amalfi before Rome, or Cinque Terre between Florence and Venice.",
    ),
})

add_trip({
    "key": "scotlandHighlands",
    "emoji": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "continent": "europe",
    "folder": "scotland-highlands",
    "title": "Scotland Highlands",
    "description": "A typical first Scotland: Edinburgh, the Highlands around Inverness, a Skye night, then Glasgow to fly home.",
    "builderNote": "The common fly-drive or rail-and-bus version of the Highlands. Add a whisky island if you have extra days.",
    "days": 9,
    "distanceKm": 780,
    "budgetAudMin": 2800,
    "budgetAudMax": 4300,
    "region": "Edinburgh · Highlands · Skye · Glasgow",
    "cover": commons("Edinburgh_Castle_from_the_south_east.jpg"),
    "highlights": [
        "Edinburgh old town and the castle ridge",
        "Loch Ness / Inverness as the Highland base",
        "Skye Cuillin views, then Glasgow for the flight",
    ],
    "gallery_files": [
        ("Edinburgh_Castle_from_the_south_east.jpg", "Edinburgh Castle"),
        ("Urquhart_Castle_and_Loch_Ness.jpg", "Urquhart Castle, Loch Ness"),
        ("Old_Man_of_Storr.jpg", "Old Man of Storr, Skye"),
        ("Glasgow_University_main_building.jpg", "University of Glasgow"),
        ("Glenfinnan_Viaduct.jpg", "Glenfinnan Viaduct"),
    ],
    "points": [
        ("Edinburgh", "United Kingdom", "start", "1", -3.1883, 55.9533),
        ("Inverness", "United Kingdom", "city", "4", -4.2247, 57.4778),
        ("Portree", "United Kingdom", "park", "6", -6.196, 57.4128),
        ("Glasgow", "United Kingdom", "end", "8", -4.2518, 55.8642),
    ],
    "lines": [
        ("Edinburgh to Inverness", "train", "4", [[-3.1883, 55.9533], [-4.2247, 57.4778]]),
        ("Inverness to Portree", "drive", "6", [[-4.2247, 57.4778], [-5.1, 57.3], [-6.196, 57.4128]]),
        ("Portree to Glasgow", "drive", "8", [[-6.196, 57.4128], [-5.1, 56.8], [-4.2518, 55.8642]]),
    ],
    "itinerary": itinerary(
        "Scotland Highlands", 9, "~780 km",
        "May–September",
        "AUD 2,800–4,300",
        "Edinburgh first, then the Highlands and Skye — the shape of most first Scottish holidays.",
        [
            ("1–3", "Edinburgh", "Royal Mile, castle, Arthur's Seat or the New Town; optional day to Stirling", "AUD 130–190"),
            ("4–5", "Inverness", "Highland rail or drive; Loch Ness, Culloden, or a short whisky visit", "AUD 120–180"),
            ("6–7", "Portree", "Skye: Old Man of Storr, Quiraing or a quieter peninsula; book rooms early", "AUD 150–220"),
            ("8–9", "Glasgow", "West-coast return; one city night and a morning flight", "AUD 110–170"),
        ],
        "- Midges are worst in still summer evenings.\n- Single-track roads on Skye need patience in high season.",
    ),
})

add_trip({
    "key": "spainClassics",
    "emoji": "🇪🇸",
    "continent": "europe",
    "folder": "spain-classics",
    "title": "Spain Classics",
    "description": "Barcelona, Madrid, and Seville — the usual first Spain by high-speed train.",
    "builderNote": "AVE links make this the default first itinerary. Add Granada's Alhambra if you can get tickets.",
    "days": 10,
    "distanceKm": 1100,
    "budgetAudMin": 3000,
    "budgetAudMax": 4600,
    "region": "Catalonia · Madrid · Andalusia",
    "cover": commons("Sagrada_Familia_01.jpg"),
    "highlights": [
        "Barcelona Gothic Quarter, beach, and Gaudí",
        "Madrid Prado / Retiro and tapas nights",
        "Seville cathedral, Alcázar, and orange-scented evenings",
    ],
    "gallery_files": [
        ("Sagrada_Familia_01.jpg", "Sagrada Família, Barcelona"),
        ("Palacio_de_Cristal%2C_Madrid%2C_Espa%C3%B1a%2C_2014-05-11%2C_DD_01.jpg", "Retiro Park, Madrid"),
        ("Catedral_de_Sevilla_y_Giralda.jpg", "Seville Cathedral and Giralda"),
        ("Park_Guell_Barcelona.jpg", "Park Güell, Barcelona"),
        ("Plaza_de_Espana_%28Seville%29.jpg", "Plaza de España, Seville"),
    ],
    "points": [
        ("Barcelona", "Spain", "start", "1", 2.1686, 41.3874),
        ("Madrid", "Spain", "city", "5", -3.7038, 40.4168),
        ("Seville", "Spain", "end", "8", -5.9845, 37.3891),
    ],
    "lines": [
        ("Barcelona to Madrid", "train", "5", [[2.1686, 41.3874], [-3.7038, 40.4168]]),
        ("Madrid to Seville", "train", "8", [[-3.7038, 40.4168], [-5.9845, 37.3891]]),
    ],
    "itinerary": itinerary(
        "Spain Classics", 10, "~1,100 km by AVE",
        "April–June, September–October",
        "AUD 3,000–4,600",
        "The first-Spain triangle: Gaudí and the Mediterranean, the capital, then Andalusia.",
        [
            ("1–4", "Barcelona", "Gothic Quarter, Sagrada Família, Barceloneta or Park Güell, one Montserrat or sitges day", "AUD 140–200"),
            ("5–7", "Madrid", "AVE west; Prado or Reina Sofía, Retiro, tapas in La Latina; Toledo day optional", "AUD 130–190"),
            ("8–10", "Seville", "AVE south; cathedral and Alcázar, Triana evening, optional Córdoba or Granada day", "AUD 130–200"),
        ],
        "- Book Sagrada Família and the Alcázar online.\n- August is hot in Seville; spring and autumn are kinder.",
    ),
})


PLACE_COPY = {
    "Sydney": {
        "country": "Australia",
        "stay": "3 nights",
        "tagline": "Harbour ferries, coastal walks, and an easy first base",
        "general": "Most Australia trips start here: Circular Quay, a ferry, a beach walk, and a day inland to the Blue Mountains.",
        "activities": ["Ferry to Manly", "Bondi to Coogee walk", "The Rocks and Opera House precinct"],
        "tips": ["Opal or contactless for trains and ferries", "Swim between the flags"],
        "itinerary": "Days 1–3 — keep the first days walkable around the harbour.",
        "photos": [photo("Sydney_Harbour_Bridge_from_Circular_Quay.jpg", "Sydney Harbour"), photo("Sydney_Opera_House_Sails.jpg", "Sydney Opera House")],
    },
    "Katoomba": {
        "country": "Australia",
        "stay": "1–2 nights",
        "tagline": "Three Sisters and Jamison Valley lookouts",
        "general": "The usual Blue Mountains overnight from Sydney — cliff walks, Scenic World if you want the railway, and cool evenings.",
        "activities": ["Three Sisters lookout", "Prince Henry Cliff Walk", "Scenic World or a waterfall track"],
        "tips": ["Train from Central is simpler than driving on weekends", "Weather turns quickly on the escarpment"],
        "itinerary": "Days 4–5 — mountains after the city.",
        "photos": [photo("Three_Sisters_Katoomba.jpg", "Three Sisters, Katoomba")],
    },
    "Canberra": {
        "country": "Australia",
        "stay": "1–2 nights",
        "tagline": "Planned capital between Sydney and Melbourne",
        "general": "A practical overnight on the inland drive: galleries, Parliament, and a lake circuit.",
        "activities": ["Australian War Memorial", "Lake Burley Griffin", "Parliamentary zone"],
        "tips": ["A car helps between precincts", "Monday some museums close"],
        "itinerary": "Days 6–7 — break the east-coast transfer.",
        "photos": [photo("Canberra_from_Mount_Ainslie.jpg", "Canberra from Mount Ainslie")],
    },
    "Melbourne": {
        "country": "Australia",
        "stay": "3 nights",
        "tagline": "Laneways, trams, and the jump-off for the Great Ocean Road",
        "general": "Coffee, galleries, and a tram-shaped city before you point west along the coast.",
        "activities": ["Laneway walk", "Tram around the loop", "Day on the peninsula or in the Yarra Valley"],
        "tips": ["Myki for trams", "Book Great Ocean Road tours if not self-driving"],
        "itinerary": "Days 8–10 — city days before the coast.",
        "photos": [photo("Flinders_Street_Station_Melbourne_2010.jpg", "Flinders Street Station")],
    },
    "Torquay": {
        "country": "Australia",
        "stay": "1–2 nights",
        "tagline": "Start of the Great Ocean Road",
        "general": "Surf town where the Great Ocean Road begins; use it as a base for Lorne and the Twelve Apostles.",
        "activities": ["Surf coast walk", "Drive toward Lorne and Apollo Bay", "Twelve Apostles at lower light"],
        "tips": ["Leave Melbourne early to beat traffic", "Apostles car parks fill by late morning"],
        "itinerary": "Days 11–12 — coastal finish.",
        "photos": [photo("Twelve_Apostles%2C_Victoria%2C_Australia.jpg", "Twelve Apostles")],
    },
    "Christchurch": {
        "country": "New Zealand",
        "stay": "2 nights",
        "tagline": "Garden-city start for a South Island drive",
        "general": "Collect a car, walk the rebuild precincts and gardens, then head inland.",
        "activities": ["Botanic Gardens", "Port Hills lookout", "Riverside market"],
        "tips": ["One-way camper drop in Queenstown is common", "Nor'west winds can be strong"],
        "itinerary": "Days 1–2 — arrival and the car.",
        "photos": [photo("Christchurch_from_the_Port_Hills.jpg", "Christchurch from the Port Hills")],
    },
    "Queenstown": {
        "country": "New Zealand",
        "stay": "3 nights",
        "tagline": "Lake Wakatipu adventure base",
        "general": "The South Island hub: lake, gondola, and day trips to vineyards or Glenorchy.",
        "activities": ["Lake walk or gondola", "Gibbston wine", "Glenorchy or a jet-boat if you want it"],
        "tips": ["Beds book out in summer", "This Queenstown is the NZ one, not Tasmania"],
        "itinerary": "Days 3–5 — lakes and day trips.",
        "photos": [photo("Queenstown_New_Zealand.jpg", "Queenstown")],
    },
    "Te Anau": {
        "country": "New Zealand",
        "stay": "2 nights",
        "tagline": "Fiordland gateway",
        "general": "Quiet lake town used as the base for Milford or Doubtful Sound.",
        "activities": ["Milford Sound day", "Lake Te Anau foreshore", "Glowworm caves if time"],
        "tips": ["Milford road can close for weather or ice", "Book cruises ahead in January"],
        "itinerary": "Days 6–7 — fiords.",
        "photos": [photo("Milford_Sound%2C_New_Zealand.jpg", "Milford Sound")],
    },
    "Wanaka": {
        "country": "New Zealand",
        "stay": "2 nights",
        "tagline": "Quieter lake than Queenstown",
        "general": "The usual calmer last stop: lake swims, a lookout walk, then back to a flight.",
        "activities": ["Lake Wanaka waterfront", "Roy's Peak or a shorter ridge", "Outlet walk"],
        "tips": ["Roy's Peak starts before dawn in season", "Fuel up before remote legs"],
        "itinerary": "Days 8–9 — quieter lake days.",
        "photos": [photo("Lake_Wanaka.jpg", "Lake Wānaka")],
    },
    "Nadi": {
        "country": "Fiji",
        "stay": "3 nights",
        "tagline": "International gateway and west-coast temples",
        "general": "Almost every Fiji trip lands here. Use it for the temple, Denarau boats, and a first reef day.",
        "activities": ["Sri Siva Subramaniya Temple", "Denarau marina", "Mamanuca day boat"],
        "tips": ["Cover shoulders at the temple", "Airport days are busy — book transfers"],
        "itinerary": "Days 1–3 — arrive and reset.",
        "photos": [photo("Sri_Siva_Subramaniya_Temple.jpg", "Sri Siva Subramaniya Temple")],
    },
    "Pacific Harbour": {
        "country": "Fiji",
        "stay": "2 nights",
        "tagline": "South-coast reefs, rivers, and Beqa",
        "general": "The adventure strip on the Coral Coast — shark dives, river trips, and a slower night than Nadi.",
        "activities": ["Beqa Lagoon snorkel or dive", "River kayak", "Arts village"],
        "tips": ["Book shark dives ahead", "Afternoons often bring showers"],
        "itinerary": "Days 4–5 — Coral Coast.",
        "photos": [photo("Beqa_Lagoon.jpg", "Beqa Lagoon")],
    },
    "Suva": {
        "country": "Fiji",
        "stay": "2 nights",
        "tagline": "Harbour capital of markets and rainforest parks",
        "general": "Fiji's political city: museum, market, and an easy forest walk at Colo-i-Suva.",
        "activities": ["Fiji Museum", "Municipal market", "Colo-i-Suva"],
        "tips": ["Weekday traffic around Victoria Parade", "Carry cash for the market"],
        "itinerary": "Days 6–7 — capital nights.",
        "photos": [photo("Suva_Fiji.jpg", "Suva")],
    },
    "Rome": {
        "country": "Italy",
        "stay": "4 nights",
        "tagline": "Historic core and the usual first Italian base",
        "general": "Start here: the Forum and Colosseum, a neighbourhood evening, and one big indoor morning.",
        "activities": ["Colosseum and Forum", "Trastevere evening", "Vatican or Appian day"],
        "tips": ["Book Vatican timed entry", "August many Romans leave town"],
        "itinerary": "Days 1–4 — walkable centre.",
        "photos": [photo("Colosseum_in_Rome%2C_Italy_-_April_2007.jpg", "Colosseum"), photo("Pantheon_Rome_1.jpg", "Pantheon")],
    },
    "Florence": {
        "country": "Italy",
        "stay": "3 nights",
        "tagline": "Duomo, galleries, and a Tuscan day",
        "general": "The middle of the classic rail triangle — dense, walkable, and an easy jump to Chianti or Pisa.",
        "activities": ["Duomo complex", "Uffizi or Accademia", "Piazzale Michelangelo at dusk"],
        "tips": ["Uffizi slots sell out", "The centro is compact — skip the car"],
        "itinerary": "Days 5–7 — Tuscany.",
        "photos": [photo("Florence_Duomo_from_Michelangelo_hill.jpg", "Florence Duomo")],
    },
    "Venice": {
        "country": "Italy",
        "stay": "3 nights",
        "tagline": "Vaporetti and quieter sestieri after the mainland",
        "general": "Finish on the water. Walk early, ride a vaporetto, and leave San Marco for off-peak hours.",
        "activities": ["Grand Canal vaporetto", "San Marco off-peak", "Cannaregio or Giudecca wander"],
        "tips": ["A 48-hour vaporetto pass usually beats single tickets", "Acqua alta season is autumn–winter"],
        "itinerary": "Days 8–10 — lagoon finish.",
        "photos": [photo("Canal_Grande_Chiesa_della_Salute_e_Dogana_dal_ponte_dell_Accademia.jpg", "Grand Canal")],
    },
    "Edinburgh": {
        "country": "United Kingdom",
        "stay": "3 nights",
        "tagline": "Castle ridge and the usual Scottish start",
        "general": "Old Town, New Town, and a hill walk before you head north.",
        "activities": ["Castle and Royal Mile", "Arthur's Seat", "New Town streets"],
        "tips": ["Festival month (August) needs rooms booked early", "Weather does four seasons in a day"],
        "itinerary": "Days 1–3 — the capital.",
        "photos": [photo("Edinburgh_Castle_from_the_south_east.jpg", "Edinburgh Castle")],
    },
    "Inverness": {
        "country": "United Kingdom",
        "stay": "2 nights",
        "tagline": "Highland railhead and Loch Ness base",
        "general": "The practical Highlands hub: loch, battlefield, and the jump toward Skye.",
        "activities": ["Loch Ness / Urquhart", "Culloden", "River Ness walk"],
        "tips": ["The sleeper or daytime rail from Edinburgh is the usual arrival", "Midges in still summer evenings"],
        "itinerary": "Days 4–5 — Highlands.",
        "photos": [photo("Urquhart_Castle_and_Loch_Ness.jpg", "Urquhart Castle")],
    },
    "Portree": {
        "country": "United Kingdom",
        "stay": "2 nights",
        "tagline": "Skye harbour town",
        "general": "The usual Skye overnight: coloured harbour, and a Storr or Quiraing morning.",
        "activities": ["Old Man of Storr", "Harbour walk", "Quiraing or a quieter peninsula"],
        "tips": ["Single-track roads and summer coaches", "Fuel and dinners book out in July"],
        "itinerary": "Days 6–7 — Skye.",
        "photos": [photo("Old_Man_of_Storr.jpg", "Old Man of Storr")],
    },
    "Glasgow": {
        "country": "United Kingdom",
        "stay": "1–2 nights",
        "tagline": "West-coast city and the usual departure airport",
        "general": "One night for music, the West End, and a morning flight.",
        "activities": ["Kelvingrove or the riverside", "West End cafes", "Mackintosh details"],
        "tips": ["Airport is west of the city — allow transfer time"],
        "itinerary": "Days 8–9 — fly-out.",
        "photos": [photo("Glasgow_University_main_building.jpg", "University of Glasgow")],
    },
    "Barcelona": {
        "country": "Spain",
        "stay": "4 nights",
        "tagline": "Gaudí, beach, and the Mediterranean start",
        "general": "Most first Spain trips begin here: Gothic streets, one big Gaudí visit, and a swim.",
        "activities": ["Gothic Quarter", "Sagrada Família", "Barceloneta or Park Güell"],
        "tips": ["Book Sagrada Família", "Pickpockets on the metro and Ramblas"],
        "itinerary": "Days 1–4 — Mediterranean city.",
        "photos": [photo("Sagrada_Familia_01.jpg", "Sagrada Família")],
    },
    "Madrid": {
        "country": "Spain",
        "stay": "3 nights",
        "tagline": "Prado, Retiro, and late dinners",
        "general": "The AVE hub in the middle of the country — museums by day, tapas after 21:00.",
        "activities": ["Prado or Reina Sofía", "Retiro", "La Latina tapas"],
        "tips": ["Many kitchens open late", "Toledo is an easy day trip"],
        "itinerary": "Days 5–7 — the capital.",
        "photos": [photo("Palacio_de_Cristal%2C_Madrid%2C_Espa%C3%B1a%2C_2014-05-11%2C_DD_01.jpg", "Retiro Park")],
    },
    "Seville": {
        "country": "Spain",
        "stay": "3 nights",
        "tagline": "Alcázar, cathedral, and Andalusian evenings",
        "general": "The usual Andalusian finish — orange trees, a big cathedral, and heat in summer.",
        "activities": ["Alcázar", "Cathedral and Giralda", "Triana evening"],
        "tips": ["Alcázar tickets online", "August afternoons are for shade"],
        "itinerary": "Days 8–10 — Andalusia.",
        "photos": [photo("Catedral_de_Sevilla_y_Giralda.jpg", "Seville Cathedral")],
    },
}


def trip_record(spec: dict) -> dict:
    folder = spec["folder"]
    gallery = [{"url": commons(name), "caption": caption} for name, caption in spec["gallery_files"]]
    return {
        "key": spec["key"],
        "emoji": spec["emoji"],
        "continent": spec["continent"],
        "folder": folder,
        "title": spec["title"],
        "description": spec["description"],
        "builderNote": spec["builderNote"],
        "geojson": f"./Trip/{folder}/route.geojson",
        "itinerary": f"./Trip/{folder}/itinerary.md",
        "days": spec["days"],
        "distanceKm": spec["distanceKm"],
        "budgetAudMin": spec["budgetAudMin"],
        "budgetAudMax": spec["budgetAudMax"],
        "region": spec["region"],
        "cover": spec["cover"],
        "highlights": spec["highlights"],
        "gallery": gallery,
    }


def write_trip_files(spec: dict) -> None:
    folder = TRIP_ROOT / spec["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    features = []
    for name, mode, day, coords in spec["lines"]:
        features.append(feature_line(name, mode, day, coords))
    for name, country, stop_type, day, lng, lat in spec["points"]:
        features.append(feature_point(name, country, stop_type, day, lng, lat))
    write_json(folder / "route.geojson", {"type": "FeatureCollection", "features": features})
    (folder / "itinerary.md").write_text(spec["itinerary"], encoding="utf-8")


def main() -> None:
    for name in OLD_FOLDERS:
        path = TRIP_ROOT / name
        if path.is_dir():
            shutil.rmtree(path)
            print(f"removed {name}")

    for spec in TRIPS:
        write_trip_files(spec)
        print(f"wrote {spec['folder']}")

    write_json(
        JOURNEYS,
        {
            "fxNote": "Budgets shown in AUD as mid-range per person, excluding long-haul flights into the region.",
            "trips": [trip_record(spec) for spec in TRIPS],
        },
    )

    details = {}
    if PLACE_DETAILS.is_file():
        details = json.loads(PLACE_DETAILS.read_text(encoding="utf-8"))
    details.update(PLACE_COPY)
    write_json(PLACE_DETAILS, details)
    print(f"Updated {len(TRIPS)} journeys and {len(PLACE_COPY)} place-detail entries")


if __name__ == "__main__":
    main()
