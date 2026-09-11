/**
 * Cities catalog handler. Platform-agnostic — exported `handle(req, res, url)`
 * is consumed by both the Vite dev plugin (`server/cities-api.js`) and the
 * Vercel serverless catch-all (`api/[...slug].js`).
 *
 * If cities.db is missing, falls back gracefully to GeoJSON-only mode, which
 * is the mode the project's dev environment has been running in.
 */
import fs from "node:fs";
import path from "node:path";
import {
  createSqlDatabaseLoader,
  makeTiersForZoom,
  parseJsonField,
  readManifestSafe,
  sendJson,
  sqlAll,
  sqlGet,
} from "../sql-shared.js";
import { PATHS } from "../paths.js";

const PARK_PLACE_RE =
  /\b(national park|nature park|national reserve|national lakes|biosphere reserve)\b/i;

const tiersForZoom = makeTiersForZoom({ thresholds: [5, 7], bottom: "town" });

const ensureSqlDatabase = createSqlDatabaseLoader({
  dbPath: PATHS.citiesDb,
  logTag: "cities-api",
  missingMessage: `City database not found at ${PATHS.citiesDb}. Run: npm run build:cities`,
});

let countryPopulationsCache = null;
const geojsonCache = new Map();

function isParkPlaceName(name) {
  return Boolean(name && PARK_PLACE_RE.test(String(name)));
}

function readCountryPopulations() {
  if (countryPopulationsCache) return countryPopulationsCache;
  if (!fs.existsSync(PATHS.countryPopulations)) {
    countryPopulationsCache = {};
    return countryPopulationsCache;
  }
  try {
    const payload = JSON.parse(fs.readFileSync(PATHS.countryPopulations, "utf-8"));
    countryPopulationsCache = payload.populations || {};
  } catch {
    countryPopulationsCache = {};
  }
  return countryPopulationsCache;
}

function cityEnrichedFlag(row) {
  if (row.enriched === 1 || row.enriched === true) return 1;
  if (row.enriched === 0 || row.enriched === false) return 0;
  const text = `${row.general || ""} ${row.tagline || ""}`;
  if (/future deep-dive/i.test(text)) return 0;
  if (row.source === "trip") return 1;
  return 0;
}

function rowToDetail(row) {
  return {
    id: row.id,
    region_id: row.region_id || "",
    name: row.name,
    country: row.country,
    cc: row.cc,
    lat: row.lat,
    lng: row.lng,
    pop: row.pop,
    tier: row.tier,
    category: row.category || "",
    locale: row.locale || "",
    source: row.source,
    general: row.general,
    tagline: row.tagline,
    stay: row.stay,
    itinerary: row.itinerary,
    activities: parseJsonField(row.activities_json ?? row.activities),
    tips: parseJsonField(row.tips_json ?? row.tips),
    photos: parseJsonField(row.photos_json ?? row.photos),
    highlights: parseJsonField(row.highlights_json ?? row.highlights),
    enriched: row.enriched ?? 0,
  };
}

function formatPopulation(pop) {
  const n = Number(pop) || 0;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

function synthesizeHighlights(detail) {
  const stored = detail.highlights || [];
  if (stored.length >= 3) return stored.filter((h) => h && h.url);
  const activities = detail.activities || [];
  const photos = detail.photos || [];
  const out = [];
  for (let i = 0; i < Math.min(6, activities.length); i += 1) {
    const text = String(activities[i] || "").trim();
    if (!text) continue;
    const title =
      text.length > 48
        ? `${text.slice(0, text.lastIndexOf(" ", 40) || 40).trim()}…`
        : text.replace(/\.$/, "");
    const photo = photos[i % photos.length];
    const url = photo?.url || photo;
    if (!url) continue;
    out.push({
      title,
      url: typeof url === "string" ? url : "",
      caption: photo?.caption || title,
      source: photo?.source || "",
    });
  }
  return out;
}

function augmentMajorCityDetail(db, detail) {
  if (!detail || detail.tier !== "major") return detail;
  const pop = Number(detail.pop) || 0;
  const country = detail.country || "";
  const regionId = detail.region_id || "europe";

  let popularity = null;
  if (db && country && pop > 0) {
    const rankRow = sqlGet(
      db,
      `SELECT COUNT(*) + 1 AS rank FROM cities WHERE country = ? AND pop > ? AND region_id = ?`,
      [country, pop, regionId]
    );
    const totalRow = sqlGet(
      db,
      `SELECT COUNT(*) AS total FROM cities WHERE country = ? AND pop > 0 AND region_id = ?`,
      [country, regionId]
    );
    const rank = rankRow?.rank || null;
    const total = totalRow?.total || 0;
    if (rank) {
      popularity = {
        rank,
        total,
        label: rank === 1 ? `Most populous in ${country}` : `#${rank} in ${country} by population`,
        population: formatPopulation(pop),
      };
    }
  }

  let nearby = [];
  if (db && detail.lat != null && detail.lng != null) {
    nearby = sqlAll(
      db,
      `SELECT id, name, country, pop, tier, lat, lng,
        (6371 * acos(min(1, max(-1,
          cos(radians(?)) * cos(radians(lat)) * cos(radians(lng) - radians(?)) +
          sin(radians(?)) * sin(radians(lat))
        )))) AS distance_km
       FROM cities
       WHERE id != ? AND region_id = ? AND pop >= 50000
         AND tier IN ('major', 'regional')
       ORDER BY distance_km
       LIMIT 10`,
      [detail.lat, detail.lng, detail.lat, detail.id, regionId]
    )
      .filter((row) => row.distance_km <= 180)
      .slice(0, 8)
      .map((row) => ({
        id: row.id,
        name: row.name,
        country: row.country,
        pop: row.pop,
        tier: row.tier,
        distanceKm: Math.round(row.distance_km),
      }));
  }

  return {
    ...detail,
    highlights: synthesizeHighlights(detail),
    nearby,
    popularity,
    isMajorCard: true,
  };
}

function featureToRow(feature) {
  const props = feature.properties || {};
  const [lng, lat] = feature.geometry?.coordinates || [props.lng, props.lat];
  return { ...props, lat: props.lat ?? lat, lng: props.lng ?? lng };
}

function loadGeojsonFeatures(regionId) {
  if (geojsonCache.has(regionId)) return geojsonCache.get(regionId);
  const manifest = readManifestSafe(PATHS.citiesManifest);
  const region = manifest?.regions?.find((item) => item.id === regionId);
  const legacy = region?.legacyGeojson;
  let geoPath = null;
  if (legacy) {
    const cleaned = legacy.replace(/^\.\//, "");
    geoPath = path.resolve(
      path.dirname(PATHS.citiesManifest),
      "..",
      cleaned.replace(/^Trip\//, "")
    );
  }
  if (!geoPath || !fs.existsSync(geoPath)) {
    geoPath = PATHS.citiesGeojson;
  }
  if (!fs.existsSync(geoPath)) {
    geojsonCache.set(regionId, []);
    return [];
  }
  const collection = JSON.parse(fs.readFileSync(geoPath, "utf-8"));
  const features = collection.features || [];
  geojsonCache.set(regionId, features);
  return features;
}

function queryFeaturesGeojson(regionId, west, south, east, north, zoom, countryCc) {
  const tiers = new Set(tiersForZoom(zoom));
  return loadGeojsonFeatures(regionId)
    .filter((feature) => {
      const row = featureToRow(feature);
      if (isParkPlaceName(row.name)) return false;
      if (!tiers.has(row.tier)) return false;
      if (countryCc && row.cc !== countryCc) return false;
      const { lat, lng } = row;
      return lat >= south && lat <= north && lng >= west && lng <= east;
    })
    .slice(0, 900)
    .map((feature) => {
      const row = featureToRow(feature);
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [row.lng, row.lat] },
        properties: {
          id: row.id,
          name: row.name,
          country: row.country,
          cc: row.cc,
          pop: row.pop,
          tier: row.tier,
          tagline: row.tagline,
          enriched: cityEnrichedFlag(row),
        },
      };
    });
}

function queryFeatures(db, regionId, west, south, east, north, zoom, countryCc) {
  if (!db) return queryFeaturesGeojson(regionId, west, south, east, north, zoom, countryCc);
  const tiers = tiersForZoom(zoom);
  const placeholders = tiers.map(() => "?").join(", ");
  const countryClause = countryCc ? " AND cc = ?" : "";
  const sql = `
    SELECT id, name, country, cc, lat, lng, pop, tier, category, locale, tagline, enriched
    FROM cities
    WHERE region_id = ?
      AND lat >= ? AND lat <= ?
      AND lng >= ? AND lng <= ?
      AND tier IN (${placeholders})${countryClause}
    LIMIT 900
  `;
  const params = [regionId, south, north, west, east, ...tiers];
  if (countryCc) params.push(countryCc);
  const rows = sqlAll(db, sql, params).filter((row) => !isParkPlaceName(row.name));
  return rows.map((row) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [row.lng, row.lat] },
    properties: {
      id: row.id,
      name: row.name,
      country: row.country,
      cc: row.cc,
      pop: row.pop,
      tier: row.tier,
      category: row.category || "",
      locale: row.locale || "",
      tagline: row.tagline,
      enriched: cityEnrichedFlag(row),
    },
  }));
}

function findCityGeojson(regionId, { id, name, country }) {
  const features = loadGeojsonFeatures(regionId);
  const match = features.find((feature) => {
    const row = featureToRow(feature);
    if (id && row.id === id) return true;
    if (name && row.name?.toLowerCase() === name.toLowerCase()) {
      if (!country || row.country?.toLowerCase() === country.toLowerCase()) return true;
    }
    return false;
  });
  return match ? featureToRow(match) : null;
}

function queryCountries(db, regionId) {
  if (!db) {
    const byCountry = new Map();
    loadGeojsonFeatures(regionId).forEach((feature) => {
      const row = featureToRow(feature);
      if (!row.country || !row.cc) return;
      const entry = byCountry.get(row.cc) || {
        country: row.country,
        cc: row.cc,
        cityCount: 0,
        bounds: { west: row.lng, east: row.lng, south: row.lat, north: row.lat },
      };
      entry.cityCount += 1;
      entry.bounds.west = Math.min(entry.bounds.west, row.lng);
      entry.bounds.east = Math.max(entry.bounds.east, row.lng);
      entry.bounds.south = Math.min(entry.bounds.south, row.lat);
      entry.bounds.north = Math.max(entry.bounds.north, row.lat);
      byCountry.set(row.cc, entry);
    });
    return [...byCountry.values()].sort((a, b) => b.cityCount - a.cityCount);
  }
  const rows = sqlAll(
    db,
    `SELECT country, cc, COUNT(*) AS city_count,
            MIN(lat) AS south, MAX(lat) AS north, MIN(lng) AS west, MAX(lng) AS east
       FROM cities
       WHERE region_id = ? AND country != '' AND cc != ''
       GROUP BY country, cc
       ORDER BY city_count DESC, country ASC`,
    [regionId]
  );
  return rows.map((row) => ({
    country: row.country,
    cc: row.cc,
    cityCount: row.city_count,
    bounds: { west: row.west, south: row.south, east: row.east, north: row.north },
  }));
}

function queryCountryPopStats(db, regionId) {
  const nationalPop = readCountryPopulations();
  const byCcMaxCity = new Map();
  if (db) {
    sqlAll(
      db,
      `SELECT cc, MAX(pop) AS max_pop FROM cities WHERE region_id = ? AND cc != '' GROUP BY cc`,
      [regionId]
    ).forEach((row) => {
      byCcMaxCity.set(row.cc, Number(row.max_pop) || 0);
    });
  } else {
    loadGeojsonFeatures(regionId).forEach((feature) => {
      const row = featureToRow(feature);
      const cc = row.cc;
      const pop = Number(row.pop) || 0;
      if (!cc || pop <= 0) return;
      const prev = byCcMaxCity.get(cc) || 0;
      if (pop > prev) byCcMaxCity.set(cc, pop);
    });
  }
  const out = {};
  const codes = new Set([...Object.keys(nationalPop), ...byCcMaxCity.keys()]);
  codes.forEach((cc) => {
    const countryPopulation = Number(nationalPop[cc]) || 0;
    const maxCityPop = byCcMaxCity.get(cc) || 0;
    out[cc] = { countryPopulation: countryPopulation || maxCityPop, maxCityPop };
  });
  return { byCc: out };
}

function getCityDetailFromDb(db, cityId) {
  if (!db) {
    const row = findCityGeojson("europe", { id: cityId });
    return row ? rowToDetail(row) : null;
  }
  const row = sqlGet(db, "SELECT * FROM cities WHERE id = ?", [cityId]);
  return row ? rowToDetail(row) : null;
}

function searchCities(db, regionId, query, limit = 12) {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  const capped = Math.min(Math.max(limit, 1), 25);
  if (!db) {
    return loadGeojsonFeatures(regionId)
      .filter((feature) => {
        const row = featureToRow(feature);
        if (isParkPlaceName(row.name)) return false;
        const name = row.name?.toLowerCase() || "";
        const country = row.country?.toLowerCase() || "";
        return name.includes(q) || country.includes(q);
      })
      .sort((a, b) => {
        const rowA = featureToRow(a);
        const rowB = featureToRow(b);
        const rank = (name) => (name === q ? 0 : name.startsWith(q) ? 1 : 2);
        const diff =
          rank(rowA.name?.toLowerCase() || "") - rank(rowB.name?.toLowerCase() || "");
        if (diff !== 0) return diff;
        return (rowB.pop || 0) - (rowA.pop || 0);
      })
      .slice(0, capped)
      .map((feature) => featureToRow(feature));
  }
  const like = `%${q}%`;
  const prefix = `${q}%`;
  return sqlAll(
    db,
    `SELECT id, name, country, cc, lat, lng, pop, tier, category, locale, tagline, enriched
       FROM cities
       WHERE region_id = ?
         AND (lower(name) LIKE ? OR lower(country) LIKE ?)
       ORDER BY
         CASE WHEN lower(name) = ? THEN 0 WHEN lower(name) LIKE ? THEN 1 ELSE 2 END,
         pop DESC
       LIMIT ?`,
    [regionId, like, like, q, prefix, capped]
  ).filter((row) => !isParkPlaceName(row.name));
}

function lookupCity(db, name, country) {
  if (!db) {
    const row = findCityGeojson("europe", { name, country });
    return row ? rowToDetail(row) : null;
  }
  const row = country
    ? sqlGet(
        db,
        "SELECT * FROM cities WHERE lower(name) = lower(?) AND lower(country) = lower(?) LIMIT 1",
        [name, country]
      )
    : sqlGet(db, "SELECT * FROM cities WHERE lower(name) = lower(?) LIMIT 1", [name]);
  return row ? rowToDetail(row) : null;
}

export async function handleCities(req, res, url) {
  if (req.method !== "GET") {
    sendJson(res, 405, { error: "Method not allowed" });
    return;
  }
  let db = null;
  try {
    db = await ensureSqlDatabase();
  } catch (error) {
    console.warn("[cities-api] DB unavailable, using GeoJSON fallback:", error?.message || error);
  }

  const pathname = url.pathname;

  if (pathname === "/api/cities/manifest") {
    const manifest = readManifestSafe(PATHS.citiesManifest);
    if (!manifest) {
      sendJson(res, 404, { error: "Manifest not found" });
      return;
    }
    sendJson(res, 200, manifest);
    return;
  }

  const countriesMatch = pathname.match(/^\/api\/cities\/([^/]+)\/countries$/);
  if (countriesMatch) {
    sendJson(res, 200, { countries: queryCountries(db, countriesMatch[1]) });
    return;
  }

  const popStatsMatch = pathname.match(/^\/api\/cities\/([^/]+)\/pop-stats$/);
  if (popStatsMatch) {
    sendJson(res, 200, queryCountryPopStats(db, popStatsMatch[1]));
    return;
  }

  const featuresMatch = pathname.match(/^\/api\/cities\/([^/]+)\/features$/);
  if (featuresMatch) {
    const regionId = featuresMatch[1];
    const west = Number(url.searchParams.get("west"));
    const south = Number(url.searchParams.get("south"));
    const east = Number(url.searchParams.get("east"));
    const north = Number(url.searchParams.get("north"));
    const zoom = Number(url.searchParams.get("zoom") || 8);
    const countryCc = (url.searchParams.get("country") || "").trim().toUpperCase() || null;
    if ([west, south, east, north].some((n) => Number.isNaN(n))) {
      sendJson(res, 400, { error: "Bounds required: west, south, east, north" });
      return;
    }
    sendJson(res, 200, {
      type: "FeatureCollection",
      features: queryFeatures(db, regionId, west, south, east, north, zoom, countryCc),
    });
    return;
  }

  const detailMatch = pathname.match(/^\/api\/cities\/detail\/([^/]+)$/);
  if (detailMatch) {
    const cityId = decodeURIComponent(detailMatch[1]);
    let detail = getCityDetailFromDb(db, cityId);
    if (!detail) {
      sendJson(res, 404, { error: "City not found" });
      return;
    }
    detail = augmentMajorCityDetail(db, detail);
    sendJson(res, 200, detail);
    return;
  }

  if (pathname === "/api/cities/lookup") {
    const name = url.searchParams.get("name") || "";
    const country = url.searchParams.get("country") || "";
    if (!name) {
      sendJson(res, 400, { error: "name is required" });
      return;
    }
    let detail = lookupCity(db, name, country);
    if (!detail) {
      sendJson(res, 404, { error: "City not found" });
      return;
    }
    detail = augmentMajorCityDetail(db, detail);
    sendJson(res, 200, detail);
    return;
  }

  if (pathname === "/api/cities/search") {
    const query = url.searchParams.get("q") || url.searchParams.get("query") || "";
    const regionId = url.searchParams.get("region") || "europe";
    const limit = Number(url.searchParams.get("limit") || 12);
    sendJson(res, 200, {
      results: searchCities(db, regionId, query, Number.isNaN(limit) ? 12 : limit),
    });
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}
