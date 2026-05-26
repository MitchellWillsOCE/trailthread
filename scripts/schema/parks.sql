PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS regions (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  park_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS parks (
  id TEXT PRIMARY KEY,
  region_id TEXT NOT NULL,
  osm_id INTEGER,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  cc TEXT NOT NULL DEFAULT '',
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  area_km2 REAL,
  biodiversity INTEGER NOT NULL DEFAULT 3,
  popularity INTEGER NOT NULL DEFAULT 50,
  tier TEXT NOT NULL DEFAULT 'regional',
  west REAL NOT NULL,
  south REAL NOT NULL,
  east REAL NOT NULL,
  north REAL NOT NULL,
  summary TEXT,
  tagline TEXT,
  stay TEXT,
  activities_json TEXT NOT NULL DEFAULT '[]',
  tips_json TEXT NOT NULL DEFAULT '[]',
  photos_json TEXT NOT NULL DEFAULT '[]',
  highlights_json TEXT NOT NULL DEFAULT '[]',
  iucn_category TEXT,
  source TEXT NOT NULL DEFAULT 'OpenStreetMap',
  enriched INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  category TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (region_id) REFERENCES regions(id)
);

CREATE INDEX IF NOT EXISTS idx_parks_region ON parks(region_id);
CREATE INDEX IF NOT EXISTS idx_parks_bounds ON parks(region_id, south, north, west, east);
CREATE INDEX IF NOT EXISTS idx_parks_tier ON parks(region_id, tier);
CREATE INDEX IF NOT EXISTS idx_parks_popularity ON parks(region_id, popularity DESC);
CREATE INDEX IF NOT EXISTS idx_parks_name ON parks(name);
CREATE INDEX IF NOT EXISTS idx_parks_enriched ON parks(region_id, enriched);
