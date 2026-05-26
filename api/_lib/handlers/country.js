/**
 * Country dossier handler. Joins cities/parks/hikes/pois SQLite databases by
 * country code. Each DB is loaded lazily and cached at module scope.
 */
import fs from "node:fs";
import {
  createSqlDatabaseLoader,
  parseJsonField,
  sendJson,
  sqlAll,
  sqlGet,
} from "../sql-shared.js";
import { PATHS } from "../paths.js";

const loaders = {
  cities: createSqlDatabaseLoader({
    dbPath: PATHS.citiesDb,
    logTag: "country-dossier:cities",
    missingMessage: `cities.db not found at ${PATHS.citiesDb}`,
  }),
  parks: createSqlDatabaseLoader({
    dbPath: PATHS.parksDb,
    logTag: "country-dossier:parks",
    missingMessage: `parks.db not found at ${PATHS.parksDb}`,
  }),
  hikes: createSqlDatabaseLoader({
    dbPath: PATHS.hikesDb,
    logTag: "country-dossier:hikes",
    missingMessage: `hikes.db not found at ${PATHS.hikesDb}`,
  }),
  pois: createSqlDatabaseLoader({
    dbPath: PATHS.poiDb,
    logTag: "country-dossier:pois",
    missingMessage: `poi.db not found at ${PATHS.poiDb}`,
  }),
};

let seasonHints = null;
function getSeasonHints() {
  if (seasonHints !== null) return seasonHints;
  try {
    seasonHints = JSON.parse(fs.readFileSync(PATHS.seasonHints, "utf-8"));
  } catch {
    seasonHints = { default: null, byCountry: {} };
  }
  return seasonHints;
}

async function loadAllDbs() {
  const out = {};
  for (const [key, loader] of Object.entries(loaders)) {
    try {
      out[key] = await loader();
    } catch (err) {
      console.warn(`[country-dossier:${key}]`, err?.message || err);
      out[key] = null;
    }
  }
  return out;
}

function topCities(db, cc) {
  if (!db) return [];
  return sqlAll(
    db,
    `SELECT id, name, country, lat, lng, pop, tier, tagline, photos_json
       FROM cities
       WHERE cc = ?
       ORDER BY CASE tier WHEN 'major' THEN 0 WHEN 'regional' THEN 1 ELSE 2 END,
                COALESCE(pop, 0) DESC
       LIMIT 6`,
    [cc.toUpperCase()]
  ).map((row) => ({
    id: row.id,
    kind: "city",
    name: row.name,
    country: row.country,
    lat: row.lat,
    lng: row.lng,
    pop: row.pop,
    tier: row.tier,
    tagline: row.tagline,
    photo: parseJsonField(row.photos_json)[0]?.url || null,
  }));
}

function topParks(db, cc) {
  if (!db) return [];
  return sqlAll(
    db,
    `SELECT id, name, country, lat, lng, tier, biodiversity, area_km2, tagline, photos_json, stay
       FROM parks
       WHERE cc = ?
       ORDER BY popularity DESC
       LIMIT 6`,
    [cc.toLowerCase()]
  ).map((row) => ({
    id: row.id,
    kind: "park",
    name: row.name,
    country: row.country,
    lat: row.lat,
    lng: row.lng,
    biodiversity: row.biodiversity,
    area_km2: row.area_km2,
    tier: row.tier,
    tagline: row.tagline,
    stay: row.stay,
    photo: parseJsonField(row.photos_json)[0]?.url || null,
  }));
}

function topHikes(db, cc) {
  if (!db) return [];
  return sqlAll(
    db,
    `SELECT id, name, country, lat, lng, length_km, difficulty, tier, tagline, photos_json
       FROM hikes
       WHERE cc = ?
       ORDER BY CASE tier WHEN 'major' THEN 0 WHEN 'regional' THEN 1 ELSE 2 END,
                popularity DESC,
                COALESCE(length_km, 0) DESC
       LIMIT 6`,
    [cc.toLowerCase()]
  ).map((row) => ({
    id: row.id,
    kind: "hike",
    name: row.name,
    country: row.country,
    lat: row.lat,
    lng: row.lng,
    length_km: row.length_km,
    difficulty: row.difficulty,
    tier: row.tier,
    tagline: row.tagline,
    photo: parseJsonField(row.photos_json)[0]?.url || null,
  }));
}

function topPois(db, cc) {
  if (!db) return [];
  return sqlAll(
    db,
    `SELECT id, name, country, lat, lng, tier, category, tagline, photos_json
       FROM pois
       WHERE cc = ?
       ORDER BY popularity DESC
       LIMIT 6`,
    [cc.toLowerCase()]
  ).map((row) => ({
    id: row.id,
    kind: "poi",
    name: row.name,
    country: row.country,
    lat: row.lat,
    lng: row.lng,
    category: row.category,
    tier: row.tier,
    tagline: row.tagline,
    photo: parseJsonField(row.photos_json)[0]?.url || null,
  }));
}

function countryHeader(citiesDb, cc) {
  if (!citiesDb) return { country: null, bounds: null };
  const row = sqlGet(
    citiesDb,
    `SELECT country,
            MIN(lat) AS south, MAX(lat) AS north,
            MIN(lng) AS west,  MAX(lng) AS east
       FROM cities
      WHERE cc = ?
      GROUP BY country
      ORDER BY COUNT(*) DESC
      LIMIT 1`,
    [cc.toUpperCase()]
  );
  if (!row) return { country: null, bounds: null };
  return {
    country: row.country,
    bounds: { west: row.west, south: row.south, east: row.east, north: row.north },
  };
}

function counts(dbs, cc) {
  const fromCount = (db, table, ccCase) => {
    if (!db) return 0;
    const r = sqlGet(db, `SELECT COUNT(*) AS c FROM ${table} WHERE cc = ?`, [ccCase]);
    return r?.c || 0;
  };
  return {
    cities: fromCount(dbs.cities, "cities", cc.toUpperCase()),
    parks: fromCount(dbs.parks, "parks", cc.toLowerCase()),
    hikes: fromCount(dbs.hikes, "hikes", cc.toLowerCase()),
    pois: fromCount(dbs.pois, "pois", cc.toLowerCase()),
  };
}

function resolveSeasonHint(countryName) {
  const hints = getSeasonHints();
  if (!countryName) return hints.default || null;
  return hints.byCountry?.[countryName] || hints.default || null;
}

export async function handleCountry(req, res, url) {
  if (req.method !== "GET") {
    sendJson(res, 405, { error: "Method not allowed" });
    return;
  }
  const match = url.pathname.match(/^\/api\/country\/([A-Za-z]{2})$/);
  if (!match) {
    sendJson(res, 404, { error: "Not found" });
    return;
  }
  const cc = match[1].toLowerCase();
  const dbs = await loadAllDbs();

  const header = countryHeader(dbs.cities, cc);
  const dossier = {
    cc,
    country: header.country,
    bounds: header.bounds,
    counts: counts(dbs, cc),
    highlights: {
      cities: topCities(dbs.cities, cc),
      parks: topParks(dbs.parks, cc),
      hikes: topHikes(dbs.hikes, cc),
      pois: topPois(dbs.pois, cc),
    },
    season: resolveSeasonHint(header.country),
  };
  if (!dossier.country && dossier.counts.cities === 0 && dossier.counts.parks === 0) {
    sendJson(res, 404, { error: "Country not in catalog" });
    return;
  }
  sendJson(res, 200, dossier);
}
