# Trailthread

A Europe-focused journey planner: an interactive map of cities, national
parks, hiking trails, and points of interest, with day-by-day itineraries,
multi-modal routing (drive / train / ferry / fly / hike), and shareable
journey codes.

```
┌────────────────────────────────────────────────────────────────┐
│  Trailthread                                                   │
│  Plan & Explore Multi-Day Routes Across Europe                 │
└────────────────────────────────────────────────────────────────┘
```

## Stack

| Layer        | Tech                                                       |
| ------------ | ---------------------------------------------------------- |
| Client       | Vite, Leaflet, vanilla ES modules                          |
| API (dev)    | Vite middleware plugins under `server/`                    |
| API (prod)   | Vercel serverless catch-all at `api/[...slug].js`          |
| Catalog data | SQLite (`sql.js`, WASM) for cities, hikes, parks, POIs     |
| Mint storage | Upstash Redis (prod) / JSON files (dev) for shared codes   |
| Build data   | Python scripts under `scripts/` (OSM, Wikidata, GeoNames)  |

The dev plugins and the production serverless function both delegate to the
same handler modules in `api/_lib/handlers/`, so there is one source of truth
for every endpoint.

## Local development

Requires Node 20+ (`.nvmrc` pins to 20). Python is only needed if you want to
rebuild the catalog databases.

```bash
npm install
npm run dev
```

Open the URL Vite prints (typically <http://localhost:5173>). The dev plugins
load the SQLite catalogs from `Trip/*/`, fall back to GeoJSON when a database
is missing, and write minted journeys to `Trip/shared-journeys/*.json`.

## API surface

All endpoints are mounted under `/api/`. The catch-all at
`api/[...slug].js` dispatches to one of six handler modules.

| Endpoint                                          | Handler          | Notes                                       |
| ------------------------------------------------- | ---------------- | ------------------------------------------- |
| `GET  /api/cities/manifest`                       | `handleCities`   | Region list + catalog metadata              |
| `GET  /api/cities/:region/features?bounds+zoom`   | `handleCities`   | Map features within a bounding box          |
| `GET  /api/cities/:region/countries`              | `handleCities`   | Country bounds + city counts                |
| `GET  /api/cities/:region/pop-stats`              | `handleCities`   | Population stats joined with country pop    |
| `GET  /api/cities/detail/:id`                     | `handleCities`   | Full record incl. nearby cities (majors)    |
| `GET  /api/cities/lookup?name=&country=`          | `handleCities`   | Resolve city by name + country              |
| `GET  /api/cities/search?q=`                      | `handleCities`   | Text search                                 |
| `GET  /api/hikes/...`                             | `handleHikes`    | Same shape as cities                        |
| `GET  /api/parks/...`                             | `handleParks`    | Same shape                                  |
| `GET  /api/poi/...`                               | `handlePoi`      | Same shape                                  |
| `GET  /api/country/:cc`                           | `handleCountry`  | Cross-catalog dossier joined on country     |
| `POST /api/journeys/create`                       | `handleJourneys` | Mint a 7-char shareable code                |
| `GET  /api/journeys/code/:code`                   | `handleJourneys` | Read the stored journey                     |
| `GET  /api/journeys/code/:code/geojson`           | `handleJourneys` | Synthesise the route geometry by mode       |

## Deploying to Vercel

The repo is configured for Vercel out of the box. `vercel.json` declares the
Vite framework preset, `dist/` as the output directory, and a `nodejs20.x`
runtime for the catch-all function.

### 1. Provision Upstash Redis (for journey codes)

Without this step the `/api/journeys/*` endpoints work on Vercel but use the
read-only bundled JSON files — minting new codes will silently fail to
persist (the file system is read-only on serverless functions).

1. Go to <https://vercel.com/marketplace> and add an **Upstash Redis**
   integration to the project.
2. Vercel will auto-provision `KV_REST_API_URL` and `KV_REST_API_TOKEN`
   environment variables. (The handler also accepts the equivalent
   `UPSTASH_REDIS_REST_*` names.)

### 2. Link and deploy

```bash
# One-time per machine:
npx vercel login

# In the repo root:
npx vercel link            # answer the prompts; choose / create the project
npx vercel env pull        # pulls the KV env vars into .env.local
npx vercel deploy          # preview deployment, prints a *.vercel.app URL
npx vercel deploy --prod   # promote to production
```

The first `vercel deploy` will trigger:
1. `npm install`
2. `npm run build` (Vite build + the `copyStaticAssetsPlugin` that copies
   `Trip/*.json`, `Trip/geo/*.geojson`, `favicon.svg`, and
   `service-worker.js` into `dist/`).
3. Bundling of `api/[...slug].js` plus all files declared in its
   `includeFiles` list (SQLite catalogs, manifests, season hints).

Cold-start cost is dominated by reading the 10 MB cities.db / hikes.db into
sql.js — expect roughly 0.5–1 s on the first request after a deploy. Warm
invocations reuse the cached `Database` instance and respond in <50 ms.

### 3. Verify the deployment

```bash
curl https://<your-deployment>.vercel.app/api/cities/manifest
curl 'https://<your-deployment>.vercel.app/api/cities/search?q=lyon'
curl 'https://<your-deployment>.vercel.app/api/country/FR'
curl https://<your-deployment>.vercel.app/api/journeys/code/SNWTFY6
```

All should return `200`. The last one is a legacy bundled journey and works
without Redis. Once Redis is wired up, `POST /api/journeys/create` will also
succeed.

## Production checklist

- [x] `npm run build` produces a complete `dist/` (HTML, hashed JS/CSS,
      service worker, favicon, repo-rooted JSON catalogs).
- [x] All six `/api/*` endpoints handled by one Vercel serverless function.
- [x] Journey codes use Upstash Redis when env vars are set; otherwise fall
      back to bundled JSON (read) / local disk (write in dev).
- [x] SQLite catalogs bundled into the function via `includeFiles`.
- [x] Service worker cache version (`SW_VERSION`) bumped so updates ship.
- [x] Static assets cached with `Cache-Control: immutable` via
      `vercel.json` headers; service worker served `no-store`.
- [ ] Rotate the `SW_VERSION` constant for every breaking client change
      (the build does not do this for you).

## Repo layout

```
api/
  [...slug].js               Vercel catch-all entrypoint
  _lib/
    handlers/*.js            Framework-agnostic handler logic
    paths.js                 Single source of truth for repo-rooted paths
    sql-shared.js            sql.js bootstrap + small helpers
server/
  _make-plugin.js            Vite plugin factory
  *-api.js                   Six thin wrappers, each ~10 lines
scripts/                     Python build/enrichment pipelines
Trip/                        Catalog data: .db files, GeoJSON, JSON, mints
docs/                        Design / roadmap notes
vite.config.js               Plugins + static-asset copy step
vercel.json                  Deployment config
```

## Rebuilding catalog data

Optional unless you're regenerating the SQLite databases:

```bash
npm run build:cities         # cities.db from GeoNames + curated seeds
npm run build:hikes          # hikes.db from OSM
npm run build:parks
npm run build:poi
npm run enrich:europe        # Pull descriptions/photos from Wikidata
```

Each task hits external APIs (OSM Overpass, Wikidata, Wikimedia) — the
user-agent string is `Trailthread/1.0`.

## License

Private. Not currently licensed for redistribution.
