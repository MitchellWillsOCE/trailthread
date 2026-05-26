PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS regions (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  hike_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hikes (
  id TEXT PRIMARY KEY,
  region_id TEXT NOT NULL,
  osm_id INTEGER,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  cc TEXT NOT NULL DEFAULT '',
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  length_km REAL,
  ascent_m INTEGER,
  difficulty TEXT,
  network TEXT,
  route_type TEXT,
  popularity INTEGER NOT NULL DEFAULT 50,
  tier TEXT NOT NULL DEFAULT 'local',
  west REAL NOT NULL,
  south REAL NOT NULL,
  east REAL NOT NULL,
  north REAL NOT NULL,
  summary TEXT,
  tagline TEXT,
  tips_json TEXT NOT NULL DEFAULT '[]',
  photos_json TEXT NOT NULL DEFAULT '[]',
  geometry_json TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'OpenStreetMap',
  enriched INTEGER NOT NULL DEFAULT 0,
  start_lat REAL,
  start_lng REAL,
  end_lat REAL,
  end_lng REAL,
  start_name TEXT,
  end_name TEXT,
  start_instructions TEXT,
  updated_at TEXT,
  FOREIGN KEY (region_id) REFERENCES regions(id)
);

CREATE INDEX IF NOT EXISTS idx_hikes_region ON hikes(region_id);
CREATE INDEX IF NOT EXISTS idx_hikes_bounds ON hikes(region_id, south, north, west, east);
CREATE INDEX IF NOT EXISTS idx_hikes_tier ON hikes(region_id, tier);
CREATE INDEX IF NOT EXISTS idx_hikes_popularity ON hikes(region_id, popularity DESC);
CREATE INDEX IF NOT EXISTS idx_hikes_name ON hikes(name);
CREATE INDEX IF NOT EXISTS idx_hikes_enriched ON hikes(region_id, enriched);
