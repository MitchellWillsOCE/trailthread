# Hiking trail database (SQLite)

Trail geometry and metadata live in **`Trip/hikes/hikes.db`**, built from OpenStreetMap via `scripts/build-hikes-db.py`.

## Enrichment (copy, tips, Commons photos)

After building the database, run:

```bash
npm run enrich:hikes
```

This uses **English Wikipedia** (near the trail centroid or by name), **Wikimedia Commons** geosearch + trail-themed text search (`collect_trail_photos` in `scripts/fetch-location-photos.py`), and merges **OSM-sourced tips** with curated safety bullets from `scripts/data/trail-enrich-tips.json`. Photo URLs are **HTTP-checked** (same idea as city enrichment) before being stored in `photos_json`.

- Prefer **`npm run enrich:hikes`** (single worker) on Windows if you see SQLite lock errors.
- Optional: `npm run enrich:hikes:parallel` uses multiple workers (faster, heavier on APIs).

Re-run the same command to process only rows with `enriched = 0`. The script adds `photos_json` and `enriched` columns automatically if your DB predates them.

## Rebuild from OSM

Curated catalog (known long-distance trails from seed lists — no random local OSM segments):

```bash
npm run build:hikes
```

Add more **notable** trails discovered from OSM (international/national walking networks, Wikidata/Wikipedia-tagged routes, min 25 km):

```bash
npm run build:hikes:known
```

Seeds live in `scripts/data/europe-hikes-seed.json` and `scripts/data/montenegro-hikes-seed.json`. Montenegro keeps only flagship routes (Via Dinarica, transversals, Durmitor) — not place-to-place GPX fragments.

Overwrites `hikes.db` (you will need to run `enrich:hikes` again afterward). Stop `npm run dev` and any `enrich:europe` job first to avoid SQLite locks on Windows.
