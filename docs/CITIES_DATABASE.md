# Global city database (Polarsteps-style)

## Storage: SQLite

City data lives in **`Trip/cities/cities.db`** (not a 5 MB JSON blob in the browser).

| Table | Purpose |
|-------|---------|
| `regions` | Region id, label, city count |
| `cities` | Coordinates, tier, copy, JSON arrays for activities/tips/photos |

Indexes support bounding-box map queries and name lookup.

## API (dev / preview)

Vite serves read-only endpoints via `server/cities-api.js`, which opens the `.db` file with **sql.js** (WebAssembly). No native `better-sqlite3` build or specific Node ABI is required.

| Endpoint | Description |
|----------|-------------|
| `GET /api/cities/manifest` | Region list and counts |
| `GET /api/cities/:region/features?west&south&east&north&zoom` | GeoJSON in viewport (tier-filtered by zoom) |
| `GET /api/cities/detail/:id` | Full city card |
| `GET /api/cities/lookup?name&country` | Resolve by name |

The map loads **only cities in the current view** from the database.

## Photo URLs (reliability)

During `enrich:cities`, each photo URL is **normalized** (e.g. `//` → `https`, `http://upload.wikimedia.org` → `https`) and checked with a **HEAD** request (fallback: short **Range GET**) before it is written to `photos_json`. URLs that do not return an image are dropped so the UI is not filled with broken thumbnails. Re-run enrichment for cities that were processed before this validation existed.

## Reset database (GeoNames + fresh SQLite)

```bash
npm run db:reset
```

Re-downloads GeoNames (if missing), rebuilds `Trip/cities/europe/*`, and rewrites `Trip/cities/cities.db`.

**Windows:** Stop `npm run dev` / `preview` first so the `.db` file is not locked (otherwise the script writes to `cities.db.build.tmp` but cannot swap it in).

## Build pipeline

```bash
# 1. Generate GeoJSON + legacy details JSON from GeoNames + seeds
npm run build:cities

# 2. Import into SQLite
npm run build:db

# 3. Enrich stubs (Wikipedia + Wikimedia + country tips, parallel workers)
npm run enrich:cities
# Or: python scripts/enrich-cities-db.py --workers 2 --photos fast
# Use `--workers 2` if you still see many HTTP 429 errors. Re-run the same command to resume (only `enriched=0` rows are processed).
```

GeoNames archive caches at `scripts/cache/cities15000.zip`.

## Enrichment sources

Multi-source pipeline (`scripts/enrichment_sources.py`) reduces Wikipedia-only rate limits:

| Source | Provides |
|--------|----------|
| **Wikidata** | Description, Commons image (P18), enwiki sitelink |
| **DBpedia** | English abstract + thumbnail JSON |
| **OSM Nominatim** | `wikipedia` tag for correct article slug |
| **Wikipedia REST** | Extract only when a sitelink is already known |
| **Wikimedia Commons** | Geosearch/text search (major/regional cities when `--photos auto/full`) |

A row is marked `enriched = 1` only when it has **at least one HTTP-verified photo** and **non-stub copy** (no “future deep-dive”). Others stay `enriched = 0` and appear as light map-only dots.

```bash
npm run enrich:europe          # paced batches until done (recommended)
npm run enrich:repair          # reset enriched rows missing photos/copy
npm run enrich:cities:batch    # single batch of 300 cities
```

- **Country tips** — `scripts/data/country-travel-tips.json`
- **Trip stops** — merged from `Trip/place-details.json` at import (marked `source: trip`)

## Client

`cities.js` calls the API. `app.js` fetches features on pan/zoom and loads each city detail on popup open.

## Legacy files

`Trip/cities/europe/cities.geojson` and `details.json` remain as build intermediates; runtime uses the database.

## Adding regions

1. Extend `build-europe-cities.py` (or add a region script).
2. Re-run `build:db`.
3. Register the region in `manifest.json`.
