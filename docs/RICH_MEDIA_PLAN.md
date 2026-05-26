# Rich media & Polarsteps-style exploration — implementation plan

This document outlines how to evolve **Trailthread** from markdown + map markers into a rich, place-first travel experience similar to [Polarsteps](https://www.polarsteps.com/) — clickable cities, photo stories, and a visual itinerary — while keeping the current Vite + Leaflet + GeoJSON architecture.

---

## Current baseline (after this pass)

| Area | Status |
|------|--------|
| Travel story panel minimize | Fixed — HUD button, panel **−** control, mobile pill, **Show story** reopen |
| Place explorer drawer | MVP — opens from map popup **Explore stop** |
| `place-details.json` | Starter entries with photos + copy |
| Itinerary richness | Tables styled as schedule; hiking modules as cards; budget grid |

---

## Phase 1 — Place-first map (2–3 days)

**Goal:** Clicking a city feels like opening a “step”, not a generic popup.

1. **Unify place keys**  
   - Add `placeId` to each GeoJSON `Point` feature (slug of `name`).  
   - Key `place-details.json` by `placeId`; keep fuzzy name match as fallback.

2. **Rich markers**  
   - Replace `circleMarker` with custom `L.divIcon` thumbnails when `photos[0]` exists.  
   - Pulse/halo on active stop; dim non-active stops while explorer is open.

3. **Explorer upgrades**  
   - Swipeable photo carousel (native scroll-snap or lightweight lib).  
   - Tabs: Overview · Photos · Tips · On this day (pull matching itinerary row).  
   - “Center on map” + “Show in itinerary” actions.

4. **Itinerary ↔ map linking**  
   - Add `data-place-id` on `.day-row` cells; click scrolls map and opens marker.  
   - Reverse: explorer “Itinerary” tab jumps to panel day row.

**Files:** `app.js`, `styles.css`, `Trip/*/route.geojson`, `Trip/place-details.json`

---

## Phase 2 — City galleries & media pipeline (3–5 days)

**Goal:** Each stop can carry a small photo story without bloating the repo.

1. **Media manifest per journey**  
   ```json
   {
     "rome": {
       "cover": "/media/bar-north/rome/cover.webp",
       "gallery": ["..."],
       "caption": "First evening in Trastevere"
     }
   }
   ```
   - Store under `Trip/<folder>/media.json` or extend `place-details.json`.  
   - Vite: copy `Trip/**/media/` to `dist` or use CDN URLs.

2. **Image optimization**  
   - Build script: resize to WebP (800 / 1600 widths), generate blur placeholders (LQIP).  
   - Lazy-load with `loading="lazy"` + `srcset`.

3. **Polarsteps-like city page (optional full-screen)**  
   - Route: hash `#place/rome` or query `?place=rome` for shareable deep links.  
   - Layout: hero image, title, country, day badge, vertical story blocks (text + 1–3 photos each).

4. **User content hook (future)**  
   - Schema fields: `source`, `takenAt`, `credit` for attribution.

---

## Phase 3 — Rich itinerary timeline (3–4 days)

**Goal:** Itinerary reads as a visual day-by-day story, not only tables.

1. **Structured itinerary format (optional migration)**  
   - Keep markdown for authoring; add `itinerary.json` generated at build time with typed days:
     ```json
     { "day": 5, "base": "Kotor", "summary": "...", "mode": "hike", "cost": [40, 70], "highlights": [] }
     ```
   - Or: markdown front-matter + remark plugin in Vite.

2. **Day card component (DOM)**  
   - Each day: left rail (day number + mode icon), centre (title + summary), right (cost pill).  
   - Expandable “Details” for hiking stats, links, booking notes.

3. **Map sync**  
   - Vertical timeline scroll spy: highlights active day’s segments on map.  
   - “Play route” animation: step through days with `map.flyTo` + temporary highlight.

4. **Modules**  
   - Hiking blocks: elevation profile (static SVG from GPX later).  
   - Budget section: keep grid; add total bar chart (CSS only).

---

## Phase 4 — Journey-level storytelling (4–6 days)

**Goal:** Whole trip feels like an explorable album.

1. **Journey cover** in trip picker: `coverImage` in `journeys.json`.  
2. **Intro story** — short markdown section rendered above itinerary (trip highlights reel).  
3. **Stats dashboard** — distance by mode, countries visited, hiking km (compute from GeoJSON).  
4. **Export / share** — static snapshot (html) or link with selected trip + place hash.

---

## Phase 5 — Advanced map (optional)

- **Clustering** for dense city stops.  
- **3D terrain** (Mapbox) or hillshade overlay for hiking legs.  
- **GPX import** per hiking module, drawn as dashed overlay.  
- **Offline PWA** — cache tiles + media for one journey.

---

## Data model reference

```typescript
// Target shape for place-details.json (v2)
interface PlaceDetail {
  placeId: string;
  name: string;
  country?: string;
  day?: string;
  stopType?: "city" | "park" | "heritage" | "start" | "end";
  general: string;
  activities: string[];
  itinerary: string;
  photos: { url: string; caption?: string; credit?: string }[];
  coordinates?: [number, number]; // lng, lat — optional override
}
```

---

## Suggested priority order

1. ✅ Panel minimize + UI labels (done)  
2. ✅ Place explorer MVP (done)  
3. Phase 1 — placeId, marker thumbnails, itinerary day links  
4. Phase 3 — day cards (biggest “rich itinerary” win)  
5. Phase 2 — media pipeline  
6. Phase 4 — journey covers & share URLs  

---

## Possible improvements (backlog)

- URL routing (`?trip=barNorth&place=kotor`) for shareable views  
- Search/filter stops in side panel  
- Dark mode tied to map basemap  
- Print-friendly itinerary PDF  
- i18n for multi-language itineraries  
- Accessibility audit (focus trap in explorer, keyboard map nav)  
- Remove duplicate/conflicting CSS during Phase 1 refactor  
- Auto-generate `place-details.json` stubs from GeoJSON point names  
- Integration with real photo EXIF + geotag import  
- Compare journeys side-by-side on split map  

---

## Technical constraints to preserve

- Stay **vanilla JS** unless complexity forces a framework.  
- **No backend required** — static hosting (Netlify, S3, GitHub Pages).  
- Trip content remains **folder-per-journey** for easy editing.  
- All new features must degrade gracefully when `photos` or `place-details` entries are missing.
