# Trailthread — expansion roadmap

Twenty possible additions for the web app, with a brief outline of how each could be achieved in the current stack (Vite, Leaflet, SQLite catalogs via `sql.js`, GeoJSON journeys).

---

## 1. Unified map search (cities + trails + journeys)

**What:** One search box with grouped results: countries, cities, trails, journey stops.

**How:** Rename `city-search` UI to neutral IDs; extend `/api/cities/search` or add `/api/search` that merges city SQL search, hike search, and in-memory journey stop index from `journeys.json`. Reuse existing `goToCityFromSearch` / `goToHikeFromSearch` handlers.

---

## 2. Shared catalog API module

**What:** Remove duplication between `cities-api.js` and `hikes-api.js` (SQL helpers, tier zoom, GeoJSON fallback).

**How:** Extract `server/catalog-api-shared.js` with `tiersForZoom`, `sendJson`, `sqlAll`, legacy loader; keep thin city/hike routers for schema-specific queries.

---

## 3. Shared explore-layer controller

**What:** One module for “explore cities / explore hikes” marker refresh, scheduling, and layer toggles instead of ~400 mirrored lines in `app.js`.

**How:** Factory `createExploreCatalog({ api, createMarker, paneId, stateKey })` used by both catalogs; single `syncExploreHudButton()` (started in current codebase).

---

## 4. Rebuild hike geometry pipeline

**What:** Persistently accurate trail polylines in `hikes.db` (no straight chords between disconnected OSM ways).

**How:** Improved `stitch_segments` in `build-hikes-db.py` (endpoint matching only); run `npm run build:hikes` / `build:hikes:full`. Optional batch script to re-fetch relations that fail stitching.

---

## 5. Offline / PWA mode

**What:** Installable app with cached basemap tiles and catalog DB for field use.

**How:** Vite PWA plugin, service worker caching static assets + `Trip/cities/cities.db` and `Trip/hikes/hikes.db`; document storage limits.

---

## 6. User accounts and saved trips

**What:** Sign in, save custom journeys, favorites for cities/trails.

**How:** Backend (Supabase/Firebase or small Node API) with auth; store user GeoJSON + metadata; manifest remains for public samples.

---

## 7. Custom journey builder

**What:** Draw or click stops on the map, assign transport modes, export GeoJSON.

**How:** Leaflet.draw or click-to-add points; reuse `routing.js` OSRM snap per leg; save to localStorage or account; generate `route.geojson` compatible with current loader.

---

## 8. Elevation profiles for trails and legs

**What:** Chart of ascent/descent along selected trail or journey leg.

**How:** Fetch elevation via Open-Elevation or Mapbox Terrain-RGB along coordinates; Chart.js canvas in trail/journey panel; store `ascent_m` in hike DB where missing.

---

## 9. Weather and best season hints

**What:** Contextual weather for stop/trail location and month.

**How:** Open-Meteo API from lat/lng; show in place/trail panels and itinerary day rows; cache by grid cell + date.

---

## 10. Photo lightbox and attribution improvements

**What:** Consistent gallery UX across popups, city sheet, trail sheet, itinerary.

**How:** Extend `media.js` carousel + lightbox; centralize Wikimedia/Commons attribution parsing; lazy-load images.

---

## 11. Itinerary map deep linking

**What:** URL hash for journey, day, stop, or trail (`#journey=…&stop=…`).

**How:** `history.replaceState` on selection; parse on load in `initializeTrips`; open panel and fly to feature.

---

## 12. Compare journeys side by side

**What:** Overlay two routes with different colors and stats comparison.

**How:** Load two trip GeoJSON layers; dual legend; panel tabs for stats diff; optional opacity slider.

---

## 13. Export and share

**What:** Export visible journey as GPX/KML/GeoJSON, share link with encoded state.

**How:** Client-side GPX builder from line features; short link service or compressed hash in URL; PDF itinerary via print CSS or `html2pdf`.

---

## 14. Trail difficulty and safety filters

**What:** Filter explore trails by SAC scale, length, country, ascent.

**How:** Extend hikes SQL queries with `WHERE difficulty IN (…)` and bounds; chips in map controls drawer; persist in `localStorage`.

---

## 15. Accessibility and keyboard map tour

**What:** Full keyboard navigation for HUD, panels, markers, and search.

**How:** Roving tabindex on marker list from search results; focus trap in dialogs; ARIA live regions for map moves; audit with axe.

---

## 16. Internationalization (i18n)

**What:** English + one or more locales for UI and place names.

**How:** JSON message catalogs; `data-i18n` or small i18n helper; optional localized city names from GeoNames alternate names field in DB.

---

## 17. Performance: vector tiles for catalogs

**What:** Smooth display of 10k+ cities without thousands of DOM markers.

**How:** Serve MVT or cluster server-side; Leaflet.VectorGrid or supercluster in client; keep detail fetch on click.

---

## 18. Journey “replay” animation

**What:** Animate progress along route with day labels and mode-colored segments.

**How:** Leaflet.MovingMarker or manual `requestAnimationFrame` interpolation along LineString; sync with itinerary scroll.

---

## 19. Community contributions / corrections

**What:** Report wrong trail geometry, suggest photos or tips.

**How:** GitHub issue template or simple form posting to webhook; admin script merges into `enrich-*-db.py` sources.

---

## 20. Admin enrichment dashboard

**What:** Internal page to preview enrichment queue, re-run photos/tips per city/trail, view stitch quality.

**How:** Small Vite sub-route or Python Flask app reading SQLite; maps preview geometry jumps (red segments); buttons to call enrichment scripts.

---

## Suggested priority order

| Phase | Items |
|-------|--------|
| Near term | 4, 1, 3, 2, 11 |
| Medium | 7, 8, 10, 14, 13 |
| Longer | 6, 5, 17, 16, 20 |

---

## Related docs

- `docs/HIKES_DATABASE.md` — hike DB build and enrichment
- `docs/RICH_MEDIA_PLAN.md` — place-first UX roadmap
- `scripts/build-hikes-db.py` — OSM relation geometry
- `routing.js` — OSRM snap for journey legs and runtime trail refine
