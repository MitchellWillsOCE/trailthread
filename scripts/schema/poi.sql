PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS regions (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  poi_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pois (
  id TEXT PRIMARY KEY,
  region_id TEXT NOT NULL,
  osm_id INTEGER,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  cc TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'heritage',
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  popularity INTEGER NOT NULL DEFAULT 60,
  tier TEXT NOT NULL DEFAULT 'regional',
  west REAL NOT NULL,
  south REAL NOT NULL,
  east REAL NOT NULL,
  north REAL NOT NULL,
  summary TEXT,
  tagline TEXT,
  activities_json TEXT NOT NULL DEFAULT '[]',
  tips_json TEXT NOT NULL DEFAULT '[]',
  photos_json TEXT NOT NULL DEFAULT '[]',
  highlights_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT 'catalog',
  enriched INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  FOREIGN KEY (region_id) REFERENCES regions(id)
);

CREATE INDEX IF NOT EXISTS idx_pois_region ON pois(region_id);
CREATE INDEX IF NOT EXISTS idx_pois_bounds ON pois(region_id, south, north, west, east);
CREATE INDEX IF NOT EXISTS idx_pois_tier ON pois(region_id, tier);
CREATE INDEX IF NOT EXISTS idx_pois_popularity ON pois(region_id, popularity DESC);
CREATE INDEX IF NOT EXISTS idx_pois_name ON pois(name);
CREATE INDEX IF NOT EXISTS idx_pois_category ON pois(region_id, category);
