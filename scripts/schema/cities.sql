PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS regions (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  city_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cities (
  id TEXT PRIMARY KEY,
  region_id TEXT NOT NULL,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  cc TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  pop INTEGER NOT NULL DEFAULT 0,
  tier TEXT NOT NULL DEFAULT 'town',
  source TEXT,
  general TEXT,
  tagline TEXT,
  stay TEXT,
  itinerary TEXT,
  activities_json TEXT NOT NULL DEFAULT '[]',
  tips_json TEXT NOT NULL DEFAULT '[]',
  photos_json TEXT NOT NULL DEFAULT '[]',
  highlights_json TEXT NOT NULL DEFAULT '[]',
  enriched INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  category TEXT NOT NULL DEFAULT '',
  locale TEXT NOT NULL DEFAULT '',
  FOREIGN KEY (region_id) REFERENCES regions(id)
);

CREATE INDEX IF NOT EXISTS idx_cities_region ON cities(region_id);
CREATE INDEX IF NOT EXISTS idx_cities_bounds ON cities(region_id, lat, lng);
CREATE INDEX IF NOT EXISTS idx_cities_tier ON cities(region_id, tier);
CREATE INDEX IF NOT EXISTS idx_cities_name_country ON cities(name, country);
CREATE INDEX IF NOT EXISTS idx_cities_enriched ON cities(region_id, enriched);
