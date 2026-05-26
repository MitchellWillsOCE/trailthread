"""Category- and locale-aware activity & tip pools for catalog cards.

Each catalog entry gets 3–4 activities and 2–3 tips picked deterministically
from a pool keyed by its `category` (and `locale`, for cities). The picker
uses a stable hash of the row id so the same place keeps the same activities
across runs, but two coastal towns 50 km apart get different combinations.

Country-specific tips are layered on top via
`scripts/data/country-travel-tips.json`.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

# ---------------------------------------------------------------------------
# City activity pools — keyed by (category, locale)
# ---------------------------------------------------------------------------

# 6–10 activities per bucket so different cities draw different subsets.
CITY_ACTIVITIES: dict[tuple[str, str], tuple[str, ...]] = {
    # ------------------------------------ COASTAL
    ("capital",    "coastal"): (
        "Walk the historic waterfront at golden hour",
        "Tour a flagship maritime or naval museum",
        "Take a ferry or harbour cruise across the bay",
        "Try the city's signature seafood dish at a local konoba/taverna",
        "Climb the city's highest viewpoint for a panoramic sweep",
        "Browse a market street where the catch is unloaded each morning",
        "Visit the old port and the lighthouse at dusk",
        "Ride a tram or vaporetto across the historic centre",
    ),
    ("metropolis", "coastal"): (
        "Walk the seafront promenade from old town to harbour",
        "Visit a flagship contemporary-art gallery near the docks",
        "Take a half-day boat trip along the coast",
        "Eat at a fish market where chefs queue for the day's catch",
        "Spend a sunset at a rooftop bar with a sea view",
        "Hop on a coastal tram or harbour ferry for the architecture",
    ),
    ("city",       "coastal"): (
        "Stroll the seafront and old harbour at dusk",
        "Climb to the citadel or ramparts above the bay",
        "Take a half-day boat tour to a nearby cove",
        "Sample the regional seafood at a quayside taverna",
        "Browse the morning fish market",
        "Walk a coastal path out of town for the panoramic view back",
        "Visit the city's archaeological or maritime museum",
    ),
    ("town",       "coastal"): (
        "Walk the seafront promenade at golden hour",
        "Eat fresh seafood at a harbourside konoba",
        "Take a small-boat tour to a nearby cove or islet",
        "Climb to a hilltop chapel or fortress for the panorama",
        "Stroll the stone-paved old town after sunset",
        "Swim from a quiet town beach in the late afternoon",
        "Buy a bottle of local wine from a family producer",
    ),
    ("village",    "coastal"): (
        "Linger at the harbour while the fishing boats unload",
        "Swim from a pebble or stone cove away from the main beach",
        "Walk the coastal path to the next bay",
        "Eat the catch-of-the-day at a family-run waterfront tavern",
        "Find the village viewpoint just above the church bell tower",
        "Buy olive oil or wine direct from a local producer",
        "Watch sunset from a sea-cliff or breakwater",
    ),
    ("hamlet",     "coastal"): (
        "Walk the single coastal lane end to end",
        "Eat the catch-of-the-day at the only taverna in town",
        "Swim from a quiet rocky cove",
        "Photograph the harbour with the village reflecting in the water",
    ),

    # ------------------------------------ ISLAND
    ("capital",    "island"): (
        "Walk the historic core in a single morning loop",
        "Take a half-day ferry to a smaller neighbouring island",
        "Eat at a backstreet taverna away from the cruise route",
        "Visit a flagship national museum dedicated to the island's history",
        "Photograph the harbour at sunset from a rooftop bar",
        "Drive (or bus) to a panoramic viewpoint outside the city",
    ),
    ("city",       "island"): (
        "Walk the old town walls or kastro",
        "Take a coastal ferry to a quieter island",
        "Eat fresh seafood at a harbourside konoba",
        "Drive the scenic loop around the island's hinterland",
        "Swim from a hidden cove signposted off the main road",
        "Buy island wine, oil, or honey direct from a producer",
    ),
    ("town",       "island"): (
        "Walk the old town's stone lanes after sunset",
        "Hop a ferry to a smaller neighbour for the day",
        "Hike the coastal path to a secluded cove",
        "Eat the catch-of-the-day at a family konoba",
        "Watch the fishing fleet return at dusk",
        "Sample the island's signature wine or rakija",
        "Climb to the kastro or chapel above the port",
    ),
    ("village",    "island"): (
        "Hike the coastal path to a secluded cove",
        "Ferry-hop to a quieter neighbour for the day",
        "Watch the fishing boats return at dusk",
        "Sample the islanders' wine or rakija at the village inn",
        "Walk the lanes between olive groves above the harbour",
        "Swim from the village's stone steps at dawn",
    ),
    ("hamlet",     "island"): (
        "Walk the single lane end-to-end",
        "Swim from the rocks behind the church",
        "Eat the catch of the day at the only taverna",
        "Photograph the hamlet from the headland",
    ),

    # ------------------------------------ MOUNTAIN
    ("capital",    "mountain"): (
        "Take the city's funicular or cable car for the panorama",
        "Walk the historic core's main square circuit",
        "Pick one flagship museum and skip the second",
        "Eat a regional alpine dish at a mountain-style inn",
        "Drive a short loop into the surrounding peaks for the view",
        "Visit the cathedral and climb its bell tower for the rooftops",
    ),
    ("city",       "mountain"): (
        "Take the funicular or cable car to the city's overlook",
        "Walk a circuit of the old town and main cathedral",
        "Sample a regional alpine or highland dish",
        "Drive a half-hour into the peaks for a panoramic viewpoint",
        "Visit a museum of mountaineering or alpine culture",
        "Walk a riverside or canyon path on the edge of the city",
    ),
    ("town",       "mountain"): (
        "Ride the local funicular or chairlift for the panorama",
        "Walk a circuit of the centro storico and main square",
        "Eat a regional alpine specialty at a wood-panelled inn",
        "Hike a marked trail to the closest panoramic viewpoint",
        "Visit an alpine produce market or cheese cellar",
        "Drive a scenic mountain pass for the views",
    ),
    ("village",    "mountain"): (
        "Hike a marked trail to a panoramic ridge above the village",
        "Sample alpine cheese, honey, or rakija direct from a producer",
        "Watch sunrise from a marked viewpoint above the village",
        "Walk the lanes between traditional stone or wooden houses",
        "Stop at a mountain refuge or chalet for a long lunch",
        "Photograph the village from a higher trail at golden hour",
    ),
    ("hamlet",     "mountain"): (
        "Walk the trail from the village square into the upper meadows",
        "Sit at the only inn and order whatever's on the day's menu",
        "Watch sunrise from the upper edge of the hamlet",
        "Photograph the cluster of stone houses from a higher path",
    ),

    # ------------------------------------ INLAND (default)
    ("capital",    "inland"): (
        "Walk the historic core in a single morning loop",
        "Pick one flagship museum and don't try to do them all",
        "Eat where the locals queue at lunchtime, not where the tourists sit",
        "Take a tram or metro across the city purely for the architecture",
        "Climb to a viewpoint above the centre for the panorama",
        "Try the city's signature regional dish at a back-street bistro",
        "Visit a flagship botanical garden or city park late afternoon",
        "Catch a free organ recital at the main cathedral if scheduled",
    ),
    ("metropolis", "inland"): (
        "Spend a morning in one historic neighbourhood, not the whole city",
        "Pick a single flagship museum — don't try to do them all",
        "Take a regional train one hour out for a contrasting day trip",
        "Eat at a market hall surrounded by produce stalls",
        "See live music in a neighbourhood venue, not a tourist hall",
        "Walk a riverside or canal stretch at dusk",
    ),
    ("city",       "inland"): (
        "Walk a circuit of the centro storico and main square",
        "Visit the cathedral and the city's flagship museum",
        "Try the regional dish at a back-street trattoria",
        "Climb the bell tower or castle for the rooftops view",
        "Browse the weekly market for produce and crafts",
        "Catch sunset from a riverside or hillside vantage point",
    ),
    ("town",       "inland"): (
        "Walk a circuit of the historic core in under an hour",
        "Eat a regional specialty at a family-run tavern",
        "Visit the town's parish church and a small local museum",
        "Browse a weekly market or seasonal festival if it's running",
        "Walk the medieval walls or riverside path",
        "Climb to a chapel or castle above town for the panorama",
        "Buy local wine, cheese, or charcuterie from a small producer",
    ),
    ("village",    "inland"): (
        "Walk the main square and parish church loop",
        "Sit at the village inn and order the day's menu",
        "Walk a back-road into the surrounding fields or vineyards",
        "Buy produce direct from a roadside farm stand",
        "Find the village viewpoint above the church",
        "Watch the church bell mark the hour from the main square",
    ),
    ("hamlet",     "inland"): (
        "Walk the single lane end-to-end",
        "Sit at the only inn for the day's home cooking",
        "Walk into the surrounding fields or woods on a farm track",
        "Photograph the cluster of houses from a nearby rise",
    ),

    # ------------------------------------ RIVERSIDE
    ("capital",    "riverside"): (
        "Walk both banks of the river and cross at least three bridges",
        "Take a sunset river cruise",
        "Eat at a riverside market hall surrounded by produce stalls",
        "Visit a museum housed in a former riverside warehouse",
        "Catch live music in a converted dockside venue",
    ),
    ("city",       "riverside"): (
        "Walk a circuit along both river banks",
        "Take a short river cruise at golden hour",
        "Eat dinner overlooking the water",
        "Visit the city's riverside museum or castle",
    ),
    ("town",       "riverside"): (
        "Walk the river path through town end-to-end",
        "Eat fish caught from the local river at a waterside tavern",
        "Cross the historic bridge at golden hour",
        "Sit on the riverbank with a coffee or local wine",
    ),
}


CITY_TIPS: dict[tuple[str, str], tuple[str, ...]] = {
    # Each pool ≥6 entries so different cities draw different mixes.
    ("capital", "coastal"): (
        "Ferries to popular islands sell out fast in summer — book ahead.",
        "Cruise-ship days swamp the old town between 09:00 and 16:00; aim for early or late.",
        "Old-town stone is slick after rain — pack grippy shoes.",
        "Tap water is fine in most coastal capitals — refill a bottle to save money.",
    ),
    ("city", "coastal"): (
        "Coastal cities heat up after 11:00 in summer — start sights early.",
        "Cruise-port days flood the old town for a few hours — check the cruise schedule.",
        "Many beaches charge for loungers; public stretches are free if you bring a towel.",
        "The first ferry of the morning is the quietest if you're island-hopping.",
    ),
    ("town", "coastal"): (
        "Cash still appears at small konobas and at harbour markets.",
        "Beach umbrellas often cost more than the parking — ask the price first.",
        "Mosquito repellent is worth packing if you sit out at dusk.",
        "The 'no shoes on stone' tradition still applies in some old towns at midday — keep flip-flops handy.",
        "Family restaurants close mid-afternoon between lunch and dinner.",
    ),
    ("village", "coastal"): (
        "Bring small notes — village shops rarely break large bills.",
        "Pharmacies and clinics may only open a few hours per day; pack what you need.",
        "Sunset is the busiest hour at the village restaurant — book a table.",
        "Tides matter at some swimming spots — check before stepping in.",
    ),
    ("hamlet", "coastal"): (
        "Don't count on an ATM — withdraw cash before you arrive.",
        "Mobile signal can be patchy between cliffs; download offline maps.",
    ),
    # ------------------------------------ ISLAND
    ("capital", "island"): (
        "Ferries to other islands run less often in winter — check the schedule.",
        "Island taxis are scarce; pre-book one if you have an early flight.",
        "Rental scooters are everywhere — wear a helmet, locals do.",
    ),
    ("city", "island"): (
        "Island weather can change quickly — bring a light layer even in summer.",
        "Boutique car rentals on islands are often cheaper than the airport chains.",
        "Cash is widely accepted but cards work in most central restaurants now.",
    ),
    ("town", "island"): (
        "Last ferry of the day is often earlier than tourists realise — confirm by 16:00.",
        "Petrol stations on islands close earlier than on the mainland.",
        "Many islands have a single ATM in the main square — withdraw extra in town.",
    ),
    ("village", "island"): (
        "Drinking water on small islands is sometimes shipped in — refill where you can.",
        "Power cuts happen occasionally on small islands — carry a torch.",
        "Bring cash; village shops don't always have card readers.",
    ),
    ("hamlet", "island"): (
        "Mobile signal is patchy on small islands — download maps before you go.",
        "Carry cash and don't count on an ATM.",
    ),
    # ------------------------------------ MOUNTAIN
    ("capital", "mountain"): (
        "Altitude changes inside the city — pack a layer even in summer.",
        "Funiculars and trams are often a faster shortcut than walking uphill.",
        "Weather can shift fast in mountain capitals — check the forecast hour by hour.",
    ),
    ("city", "mountain"): (
        "Pack walking shoes for cobbles and a layer for evenings even in July.",
        "Cable cars often close in high wind — confirm before buying tickets.",
        "Daylight is shorter inside valleys than on open coast — plan sunset early.",
    ),
    ("town", "mountain"): (
        "Mountain roads can be narrow and switch-backed — allow extra driving time.",
        "Refuges and chalets need cash for lunch in many areas.",
        "Mosquito repellent is worth packing near lakes and meadows.",
        "Carry a light layer — peaks stay cold even in midsummer.",
    ),
    ("village", "mountain"): (
        "Village shops close mid-afternoon — buy lunch supplies in the morning.",
        "Carry water — village fountains are usually safe but not guaranteed.",
        "Sunrise and sunset are colder than the day temperature suggests.",
    ),
    ("hamlet", "mountain"): (
        "Carry cash, water, and a layer — the nearest shop may be 20 minutes away.",
        "Mobile signal is unreliable; download offline maps.",
    ),
    # ------------------------------------ INLAND
    ("capital", "inland"): (
        "Many flagship museums close one weekday — check before you go.",
        "City transit cards usually bundle museum discounts — worth the upfront cost.",
        "Sunday closures hit shops and offices, not restaurants.",
        "Reserved-seat trains are sometimes much cheaper booked two weeks ahead.",
    ),
    ("metropolis", "inland"): (
        "Pick a single neighbourhood rather than trying to see everything.",
        "Tourist crowds peak between 10:00 and 16:00 at flagship sights — visit early or late.",
        "Late August empties some quarters but fills the parks — plan accordingly.",
    ),
    ("city", "inland"): (
        "Most museums shut one weekday — usually Monday or Tuesday.",
        "Regional train tickets sometimes need stamping or scanning before boarding.",
        "Cash still appears at smaller bakeries and family restaurants.",
        "Lunch menus are often half the price of evening menus for the same dish.",
    ),
    ("town", "inland"): (
        "Sundays are quiet — shops close, restaurants stay open.",
        "Tourist offices in smaller towns have free walking-tour maps worth grabbing.",
        "Carry small change for parking meters and toilets.",
        "August can empty offices but fills the historic core with day-trippers.",
    ),
    ("village", "inland"): (
        "Village shops keep short hours; buy lunch supplies before noon.",
        "ATMs may be a few villages away — carry small cash.",
        "Sunday and feast-day services pause shops and restaurants for a few hours.",
    ),
    ("hamlet", "inland"): (
        "Don't count on an ATM — withdraw cash before you arrive.",
        "Mobile signal can be patchy in deep valleys; download offline maps.",
    ),
}


# ---------------------------------------------------------------------------
# Park activity & tip pools — keyed by park category
# ---------------------------------------------------------------------------

PARK_ACTIVITIES: dict[str, tuple[str, ...]] = {
    "national-park": (
        "Walk the main signposted loop trail",
        "Visit the park visitor centre for the orientation film",
        "Drive (or bus) the scenic park road end-to-end",
        "Photograph the headline viewpoint at golden hour",
        "Look for wildlife at dawn from a quiet pull-out",
        "Pack a picnic for one of the marked rest areas",
        "Join a ranger-led walk if the schedule has one running",
    ),
    "marine-park": (
        "Snorkel the marked underwater trail or reef",
        "Take a glass-bottom or RIB tour from the visitor port",
        "Walk the coastal path between marked viewpoints",
        "Swim from a stone or pebble cove away from the main beach",
        "Watch for dolphins or turtles from the cliff-top trails",
        "Eat fresh-caught fish at the park-edge taverna",
    ),
    "coastal-park": (
        "Walk the cliff-top path from viewpoint to viewpoint",
        "Swim from a pebble cove signposted off the trail",
        "Photograph sea stacks or arches at golden hour",
        "Birdwatch from a hide along the wetlands or estuary",
        "Cycle the coastal greenway end-to-end if available",
    ),
    "lake-park": (
        "Take a boat trip or kayak across the main lake",
        "Walk the lakeside boardwalks between waterfalls",
        "Photograph reflections on a still morning",
        "Hike from one lake basin up to the next",
        "Find a quieter shore at dusk and watch the light change",
    ),
    "mountain-park": (
        "Hike to the most-photographed panoramic viewpoint",
        "Take the cable car or funicular to the upper plateau",
        "Stay overnight at a mountain refuge for sunrise",
        "Walk a ridge trail between two valleys",
        "Photograph the high peaks at first light",
        "Pack layers — the summit is always colder than the trailhead",
    ),
    "forest-park": (
        "Walk a boardwalk circuit between ancient trees",
        "Spot wildlife at dawn from a marked hide",
        "Cycle a quiet forest road end-to-end",
        "Photograph the canopy from the visitor-centre tower",
        "Take an interpreted nature walk if a ranger is on duty",
    ),
    "archaeological-park": (
        "Walk the excavated main road or processional way",
        "Visit the on-site museum for context before the ruins",
        "Hire a licensed guide for an hour at the entrance",
        "Visit at golden hour when crowds thin and stone glows",
        "Bring water and sun cover — most ruins have no shade",
    ),
    "geopark": (
        "Take a guided cave or karst tour if available",
        "Walk the signposted geological trail between formations",
        "Photograph the karst landscape at golden hour",
        "Visit the visitor centre for the geological orientation",
    ),
    "nature-reserve": (
        "Walk the signposted main trail end-to-end",
        "Birdwatch from one of the marked hides at dawn",
        "Take an interpreted ranger walk if available",
        "Pack a picnic for a marked rest area",
        "Photograph the headline habitat at golden hour",
    ),
}

PARK_TIPS: dict[str, tuple[str, ...]] = {
    "national-park": (
        "Buy timed-entry tickets online in peak season — gates can sell out by 10:00.",
        "Stay on marked trails to protect fragile habitats and avoid fines.",
        "Mobile signal is patchy inside most parks; download offline maps before entering.",
        "Pack water and snacks — facilities inside the park are sparse and pricey.",
        "Early morning and late afternoon are the quietest hours at the headline viewpoints.",
    ),
    "marine-park": (
        "Anchoring is forbidden on most reef trails — moor at marked buoys only.",
        "Reef-safe sunscreen is required in many marine parks — bring some from home.",
        "Wear water shoes — most coves are rocky, not sandy.",
        "Check sea conditions before snorkelling; afternoon wind picks up in summer.",
    ),
    "coastal-park": (
        "Cliff edges erode — stay behind ropes and fences.",
        "Tides change quickly at some beaches — check times before walking out far.",
        "Wind can be strong on exposed paths; pack a light shell even on hot days.",
    ),
    "lake-park": (
        "Boardwalks can be slippery after rain — grippy shoes help.",
        "Water levels change seasonally; some boardwalks close in spring snowmelt.",
        "Boat tickets often sell out in summer — book the first or last departure.",
    ),
    "mountain-park": (
        "Carry layers — peak temperatures can swing 15°C from valley to summit.",
        "Storms build fast in the afternoon — start summit hikes early.",
        "Cable cars close in high wind; check the weather before you commit.",
        "Refuges and huts need cash for lunch in many areas.",
    ),
    "forest-park": (
        "Tick season runs spring through autumn; tuck trousers into socks on grassy trails.",
        "Mosquito repellent is worth packing near streams and meadows.",
        "Some forest tracks are open to logging trucks on weekdays — give way.",
    ),
    "archaeological-park": (
        "Bring water and sun cover — most ruin sites have no shade.",
        "A licensed guide for the first hour is worth far more than the audio guide.",
        "Photography is fine but flash and tripods are often restricted.",
    ),
    "geopark": (
        "Cave tours fill in advance — book ahead in peak season.",
        "Cave temperatures hover around 10°C year-round — bring a fleece.",
        "Drone use is restricted in many geological sites.",
    ),
    "nature-reserve": (
        "Stick to marked paths — many reserves protect ground-nesting birds.",
        "Dawn and dusk are the wildlife-active hours; midday is quiet.",
        "Some reserves require a free permit at the visitor centre.",
    ),
}


# ---------------------------------------------------------------------------
# POI activity & tip pools — keyed by refined POI category
# ---------------------------------------------------------------------------

POI_ACTIVITIES: dict[str, tuple[str, ...]] = {
    "fortress": (
        "Walk the full circuit of the ramparts at dusk",
        "Climb the keep or main tower for the panorama",
        "Visit the small site museum for the siege history",
        "Photograph the walls from the river or sea side",
        "Sit at a café below the gates as the lights come on",
        "Allow time for the secondary bastions, not just the main keep",
    ),
    "palace": (
        "Tour the state rooms and royal apartments",
        "Walk the formal gardens in the late afternoon light",
        "Visit any palace chapel or treasure room included with the ticket",
        "Look up — palace ceilings are often more remarkable than the walls",
        "Skip the entrance queue with a timed-entry ticket booked online",
    ),
    "cathedral": (
        "Walk the nave from west door to apse",
        "Climb the bell tower or dome for the rooftops view",
        "Visit the crypt or treasury — usually a few coins extra",
        "Sit through a few minutes of choral service if one is running",
        "Photograph the rose window from inside at midday",
    ),
    "monastery": (
        "Walk the cloister at the quietest hour, mid-morning",
        "View the church frescoes from the back, not the centre aisle",
        "Visit the monastery shop for honey, herbs, or icons",
        "Time your visit between services — chapel access is restricted otherwise",
        "Photograph the complex from the surrounding hillside, not the entrance",
    ),
    "bridge": (
        "Walk across at golden hour for the best light",
        "Photograph the bridge from both river banks",
        "Visit the small bridge museum if one is open",
        "Find a riverside café with the bridge in view for an aperitif",
    ),
    "archaeological": (
        "Walk the excavated main road or processional way",
        "Visit the on-site museum before stepping into the ruins",
        "Hire a licensed guide for the first hour at the gate",
        "Visit at golden hour — stone glows and crowds thin",
        "Bring water and sun cover; ancient sites rarely have shade",
    ),
    "mountain": (
        "Take the cable car or cog railway to the upper viewpoint",
        "Hike to the panoramic vantage from the valley floor",
        "Photograph the peak at first or last light",
        "Visit the mountain hut for lunch and a long coffee",
        "Wait for clouds to lift — the summit changes character every hour",
    ),
    "monument": (
        "Walk a full circuit, not just the front view",
        "Visit at golden hour for the photo",
        "Check whether the monument has a visitor centre or interpretation hall",
        "Read the on-site panels — most monuments reward 10 minutes of context",
    ),
    "museum": (
        "Pick one or two galleries — full visits rarely beat focused ones",
        "Use the audio guide for the headline rooms only",
        "Visit late afternoon if a flagship — crowds thin after 16:00",
        "Check the temporary exhibition — sometimes more memorable than the permanent one",
    ),
    "heritage": (
        "Walk the site's main route end-to-end before doubling back",
        "Visit the interpretation centre for the historical context",
        "Photograph the site at golden hour from a higher vantage",
        "Allow at least 90 minutes — most heritage sites reward slow walking",
    ),
    "landmark": (
        "Visit at golden hour for the best photo",
        "Walk a full circuit, not just the headline view",
        "Check whether nearby cafés have a better angle than the official viewpoint",
        "Read the on-site panels — even short context changes how a place reads",
    ),
}

POI_TIPS: dict[str, tuple[str, ...]] = {
    "fortress": (
        "Stone steps and uneven floors — grippy shoes help, no heels.",
        "Most fortress walls have no railings on the inner side — keep an eye on children.",
        "Carry water and sun cover — fortresses rarely have shade.",
        "Sunset closing time is often an hour before official sunset.",
    ),
    "palace": (
        "State-room visits are usually timed; book online to skip the queue.",
        "Big bags and tripods are restricted in most state rooms — leave them at the hotel.",
        "Don't try to do the gardens AND the interior in one visit — pick one.",
    ),
    "cathedral": (
        "Cover shoulders and knees — dress codes are enforced at major cathedrals.",
        "Tower climbs are usually narrow and one-way — skip if claustrophobic.",
        "Photography is fine but flash is rarely allowed.",
        "Free Sunday services let you experience the building without an entrance fee.",
    ),
    "monastery": (
        "Cover shoulders and knees — dress codes are strictly enforced.",
        "Silence in cloisters and chapels is expected, not optional.",
        "Some monasteries close to visitors during service hours — check schedule.",
        "Photography inside chapels is often forbidden — look for posted icons.",
    ),
    "bridge": (
        "Bridges get slippery in rain — grippy shoes if it's wet.",
        "Selfie spots can clog one side — cross and shoot from the opposite bank.",
        "Sunset crowds peak ~30 minutes before golden hour — get there early.",
    ),
    "archaeological": (
        "Bring water and sun cover — most ruins offer almost no shade.",
        "A licensed guide for one hour explains far more than an audio guide.",
        "Stay on marked paths — fines apply for crossing rope barriers.",
        "Photography is fine; flash and tripods are often restricted.",
    ),
    "mountain": (
        "Pack layers — summit temperatures stay 10-15°C colder than the valley.",
        "Cable cars close in high wind — check the operator's status before leaving the hotel.",
        "Refuges accept cash only in many places; bring some.",
        "Storms build fast in the afternoon — start any hike early.",
    ),
    "monument": (
        "Selfie crowds peak between 11:00 and 15:00 — visit early or late.",
        "Many monuments are floodlit at night — worth a return visit after sunset.",
        "Look for the official viewpoint marker — usually a better photo than the entrance.",
    ),
    "museum": (
        "Most flagship museums close one weekday — check before you go.",
        "Coat-check is often mandatory for large bags.",
        "Free admission days exist at many national museums — usually one Sunday a month.",
    ),
    "heritage": (
        "Carry water, sun cover, and a torch for any underground passages.",
        "Photography is fine in most heritage sites; flash and tripods restricted.",
        "Visit early to beat tour groups arriving from nearby cruise ports.",
    ),
    "landmark": (
        "The most-photographed angle is rarely the entrance — walk around first.",
        "Visit at golden hour; midday light flattens most architecture.",
        "Combine with a nearby café visit — most landmarks reward unhurried looking.",
    ),
}


# ---------------------------------------------------------------------------
# Deterministic picker
# ---------------------------------------------------------------------------


def _hash_int(seed: str) -> int:
    return int(hashlib.md5((seed or "").encode("utf-8")).hexdigest(), 16)


def pick_from_pool(pool: Iterable[str], seed: str, count: int) -> list[str]:
    """Deterministically choose `count` distinct items from `pool` using `seed`.

    Builds a stable permutation of indices via per-item hashes so adjacent
    seeds draw different combinations, and items are never re-picked.
    """
    items = list(pool or ())
    if not items or count <= 0:
        return []
    if count >= len(items):
        return list(items)
    order = sorted(range(len(items)), key=lambda i: _hash_int(f"{seed}#{i}"))
    return [items[i] for i in order[:count]]


def city_activities(category: str, locale: str, seed: str) -> list[str]:
    pool = (
        CITY_ACTIVITIES.get((category, locale))
        or CITY_ACTIVITIES.get((category, "inland"))
        or CITY_ACTIVITIES.get(("town", locale))
        or CITY_ACTIVITIES.get(("town", "inland"), ())
    )
    return pick_from_pool(pool, seed, 4)


def city_tips(category: str, locale: str, country: str, seed: str, country_tips: list[str] | None = None) -> list[str]:
    pool = (
        CITY_TIPS.get((category, locale))
        or CITY_TIPS.get((category, "inland"))
        or CITY_TIPS.get(("town", locale))
        or CITY_TIPS.get(("town", "inland"), ())
    )
    chosen = pick_from_pool(pool, seed, 2)
    if country_tips:
        chosen.append(pick_from_pool(country_tips, seed + "/country", 1)[0])
    return chosen[:3]


def park_activities(category: str, seed: str) -> list[str]:
    pool = PARK_ACTIVITIES.get(category) or PARK_ACTIVITIES["national-park"]
    return pick_from_pool(pool, seed, 4)


def park_tips(category: str, seed: str) -> list[str]:
    pool = PARK_TIPS.get(category) or PARK_TIPS["national-park"]
    return pick_from_pool(pool, seed, 3)


def poi_activities(category: str, seed: str) -> list[str]:
    pool = POI_ACTIVITIES.get(category) or POI_ACTIVITIES["landmark"]
    return pick_from_pool(pool, seed, 4)


def poi_tips(category: str, seed: str) -> list[str]:
    pool = POI_TIPS.get(category) or POI_TIPS["landmark"]
    return pick_from_pool(pool, seed, 3)


# ---------------------------------------------------------------------------
# Generic-template detection (used to decide whether to overwrite)
# ---------------------------------------------------------------------------

GENERIC_ACTIVITY_PATTERNS = (
    "Stroll the historic centre of",
    "Find a local café or market",
    "Find a local cafe or market",
    "Catch sunset from a viewpoint",
    "Follow marked trails through",
    "Visit the main visitor centre and orientation exhibits",
    "Photograph viewpoints at golden hour",
    "Join a ranger-led walk if available",
    "Walk the main approach to",
    "Read on-site panels about",
    "Allow time for photos in the best light",
    "Old town walk",
    "Local food market",
    "Local café stop",
    "Viewpoint visit",
    "Viewpoint sunset",
)

# Imperative verbs that signal a "real" actionable activity. Curated
# entries (Rome's "Trastevere food crawl") read as noun phrases — those
# are caught by the curated-noun-phrase test below.
_ACTIVITY_VERBS = {
    "walk", "stroll", "hike", "climb", "visit", "tour", "take", "ride",
    "drive", "cycle", "ferry", "boat", "swim", "browse", "shop", "eat",
    "dine", "try", "sample", "taste", "sit", "sip", "watch", "stay",
    "spend", "see", "photograph", "shoot", "find", "look", "wait",
    "linger", "buy", "rent", "follow", "join", "skip", "wander",
    "explore", "catch", "read", "allow", "pack",
}


def _looks_like_wikipedia_sentence(text: str) -> bool:
    """Heuristic for descriptive sentences that snuck in from a Wikipedia summary.

    Wikipedia summaries start with articles/pronouns and end with a full stop,
    often contain dates or proper-noun chains, and never start with an
    imperative verb.
    """
    if not text or not text.endswith("."):
        return False
    if len(text) < 30:
        return False
    first = text.split(" ", 1)[0].lower().rstrip(",")
    if first in _ACTIVITY_VERBS:
        return False
    if first in {
        "it", "its", "the", "a", "an", "this", "these", "they", "he",
        "she", "we", "many", "most", "some", "with", "after", "before",
        "during", "in", "by", "on", "at", "as", "founded", "built",
        "named", "known", "originally", "later", "today",
    }:
        return True
    # Multi-sentence stuffing
    if text.count(". ") >= 1 and any(c.isdigit() for c in text):
        return True
    return False


def looks_like_generic_activities(activities: list[str]) -> bool:
    """Return True if the list looks like the legacy template pool or
    Wikipedia-sentence stuffing, so the row should be refreshed.

    Curated activities (e.g. "Trastevere food crawl", "City walls circuit")
    will NOT match — they read as short imperative or noun-phrase actions.
    The threshold is a majority of "bad" entries so that one stray
    Wikipedia sentence next to two real curated activities is preserved,
    but two Wikipedia sentences alongside one template fallback (the
    Tower-of-London case) gets refreshed.
    """
    if not activities:
        return True
    bad = 0
    total = 0
    for line in activities:
        text = (line or "").strip()
        if not text:
            bad += 1
            total += 1
            continue
        total += 1
        if any(pat in text for pat in GENERIC_ACTIVITY_PATTERNS):
            bad += 1
            continue
        if _looks_like_wikipedia_sentence(text):
            bad += 1
            continue
    # Majority bad → refresh (handles 2/3 Wikipedia + 1 template combos)
    return bad * 2 >= total and bad >= 1
