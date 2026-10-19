import fs from "node:fs";
import path from "node:path";
import {
  attachCoverUrls,
  catalogCoverForRow,
  createSqlDatabaseLoader,
  makeTiersForZoom,
  parseJsonField,
  readManifestSafe,
  sendJson,
  sqlAll,
  sqlGet,
} from "../sql-shared.js";
import { PATHS } from "../paths.js";

const tiersForZoom = makeTiersForZoom({ thresholds: [7, 9], bottom: "local" });

const ensureSqlDatabase = createSqlDatabaseLoader({
  dbPath: PATHS.hikesDb,
  logTag: "hikes-api",
  missingMessage: `Hike database not found at ${PATHS.hikesDb}. Run: npm run build:hikes`,
});

const geojsonCache = new Map();

function parseGeometry(rawValue) {
  if (rawValue === null || rawValue === undefined || rawValue === "") {
    return { type: "LineString", coordinates: [] };
  }
  let parsed;
  if (typeof rawValue === "string") {
    try {
      parsed = JSON.parse(rawValue);
    } catch {
      return { type: "LineString", coordinates: [] };
    }
  } else {
    parsed = rawValue;
  }
  if (
    parsed &&
    typeof parsed === "object" &&
    !Array.isArray(parsed) &&
    typeof parsed.type === "string" &&
    Array.isArray(parsed.coordinates) &&
    (parsed.type === "LineString" || parsed.type === "MultiLineString")
  ) {
    return parsed;
  }
  if (Array.isArray(parsed)) {
    if (parsed.length && Array.isArray(parsed[0]) && typeof parsed[0][0] === "number") {
      return { type: "LineString", coordinates: parsed };
    }
    if (parsed.length && Array.isArray(parsed[0]) && Array.isArray(parsed[0][0])) {
      return { type: "MultiLineString", coordinates: parsed };
    }
  }
  return { type: "LineString", coordinates: [] };
}

function rowToDetail(row) {
  const geometry = parseGeometry(row.geometry_json);
  const start =
    row.start_lat != null && row.start_lng != null
      ? { lat: row.start_lat, lng: row.start_lng, name: row.start_name || null }
      : null;
  const end =
    row.end_lat != null && row.end_lng != null
      ? { lat: row.end_lat, lng: row.end_lng, name: row.end_name || null }
      : null;
  return {
    id: row.id,
    osm_id: row.osm_id,
    name: row.name,
    country: row.country,
    cc: row.cc,
    lat: row.lat,
    lng: row.lng,
    length_km: row.length_km,
    ascent_m: row.ascent_m,
    difficulty: row.difficulty,
    network: row.network,
    route_type: row.route_type,
    popularity: row.popularity,
    tier: row.tier,
    summary: row.summary,
    tagline: row.tagline,
    tips: parseJsonField(row.tips_json),
    photos: parseJsonField(row.photos_json ?? row.photos),
    source: row.source,
    geometry,
    start,
    end,
    start_instructions: row.start_instructions || null,
  };
}

function loadGeojsonFeatures(regionId) {
  if (geojsonCache.has(regionId)) return geojsonCache.get(regionId);
  const manifest = readManifestSafe(PATHS.hikesManifest);
  const region = manifest?.regions?.find((item) => item.id === regionId);
  const legacy = region?.legacyGeojson;
  if (!legacy) {
    geojsonCache.set(regionId, []);
    return [];
  }
  const geoPath = path.resolve(
    path.dirname(PATHS.hikesManifest),
    "..",
    legacy.replace(/^\.\//, "").replace(/^Trip\//, "")
  );
  if (!fs.existsSync(geoPath)) {
    geojsonCache.set(regionId, []);
    return [];
  }
  const features = (JSON.parse(fs.readFileSync(geoPath, "utf-8")).features) || [];
  geojsonCache.set(regionId, features);
  return features;
}

function queryFeatures(db, regionId, west, south, east, north, zoom, countryCc) {
  if (!db) {
    const tiers = new Set(tiersForZoom(zoom));
    return loadGeojsonFeatures(regionId)
      .filter((feature) => {
        const props = feature.properties || {};
        if (!tiers.has(props.tier)) return false;
        if (countryCc && props.cc !== countryCc) return false;
        const [lng, lat] = feature.geometry?.coordinates || [0, 0];
        return lat >= south && lat <= north && lng >= west && lng <= east;
      })
      .sort((a, b) => (b.properties?.popularity || 0) - (a.properties?.popularity || 0))
      .slice(0, 400)
      .map((feature) => {
        const cover = catalogCoverForRow(feature.properties || {});
        if (!cover) return feature;
        return {
          ...feature,
          properties: { ...(feature.properties || {}), cover },
        };
      });
  }
  const tiers = tiersForZoom(zoom);
  const placeholders = tiers.map(() => "?").join(", ");
  const countryClause = countryCc ? " AND cc = ?" : "";
  const sql = `
    SELECT id, name, country, cc, lat, lng, length_km, ascent_m, difficulty,
           network, popularity, tier, tagline
    FROM hikes
    WHERE region_id = ?
      AND lat >= ? AND lat <= ?
      AND lng >= ? AND lng <= ?
      AND tier IN (${placeholders})${countryClause}
    ORDER BY popularity DESC
    LIMIT 400
  `;
  const params = [regionId, south, north, west, east, ...tiers];
  if (countryCc) params.push(countryCc);
  const rows = sqlAll(db, sql, params);
  attachCoverUrls(db, "hikes", rows);
  return rows.map((row) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [row.lng, row.lat] },
    properties: {
      id: row.id,
      name: row.name,
      country: row.country,
      cc: row.cc,
      length_km: row.length_km,
      ascent_m: row.ascent_m,
      difficulty: row.difficulty,
      network: row.network,
      popularity: row.popularity,
      tier: row.tier,
      tagline: row.tagline,
      ...(row.cover ? { cover: row.cover } : {}),
    },
  }));
}

function getHikeDetail(db, hikeId) {
  if (!db) {
    const feature = loadGeojsonFeatures("europe").find((f) => f.properties?.id === hikeId);
    if (!feature) return null;
    return {
      id: feature.properties.id,
      name: feature.properties.name,
      country: feature.properties.country,
      lat: feature.geometry.coordinates[1],
      lng: feature.geometry.coordinates[0],
      length_km: feature.properties.length_km,
      popularity: feature.properties.popularity,
      tier: feature.properties.tier,
      tagline: feature.properties.tagline,
      summary: `${feature.properties.name} hiking route.`,
      tips: [],
      photos: [],
      geometry: { type: "LineString", coordinates: [] },
      source: "OpenStreetMap",
    };
  }
  const row = sqlGet(db, "SELECT * FROM hikes WHERE id = ?", [hikeId]);
  return row ? rowToDetail(row) : null;
}

function searchHikes(db, regionId, query, limit = 12) {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  if (!db) {
    return loadGeojsonFeatures(regionId)
      .filter((f) => f.properties?.name?.toLowerCase().includes(q))
      .sort((a, b) => (b.properties?.popularity || 0) - (a.properties?.popularity || 0))
      .slice(0, limit)
      .map((f) => ({
        id: f.properties.id,
        name: f.properties.name,
        country: f.properties.country,
        lat: f.geometry.coordinates[1],
        lng: f.geometry.coordinates[0],
        length_km: f.properties.length_km,
        popularity: f.properties.popularity,
        tier: f.properties.tier,
        tagline: f.properties.tagline,
      }));
  }
  const like = `%${q}%`;
  const prefix = `${q}%`;
  return sqlAll(
    db,
    `SELECT id, name, country, cc, lat, lng, length_km, popularity, tier, tagline
       FROM hikes
       WHERE region_id = ?
         AND (lower(name) LIKE ? OR lower(country) LIKE ?)
       ORDER BY
         CASE WHEN lower(name) = ? THEN 0 WHEN lower(name) LIKE ? THEN 1 ELSE 2 END,
         popularity DESC
       LIMIT ?`,
    [regionId, like, like, q, prefix, limit]
  );
}

export async function handleHikes(req, res, url) {
  if (req.method !== "GET") {
    sendJson(res, 405, { error: "Method not allowed" });
    return;
  }
  let db = null;
  try {
    db = await ensureSqlDatabase();
  } catch (error) {
    console.warn("[hikes-api] DB unavailable, GeoJSON fallback:", error?.message || error);
  }

  const pathname = url.pathname;

  if (pathname === "/api/hikes/manifest") {
    const manifest = readManifestSafe(PATHS.hikesManifest);
    if (!manifest) {
      sendJson(res, 404, { error: "Manifest not found" });
      return;
    }
    sendJson(res, 200, manifest);
    return;
  }

  const featuresMatch = pathname.match(/^\/api\/hikes\/([^/]+)\/features$/);
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

  const detailMatch = pathname.match(/^\/api\/hikes\/detail\/([^/]+)$/);
  if (detailMatch) {
    const detail = getHikeDetail(db, decodeURIComponent(detailMatch[1]));
    if (!detail) {
      sendJson(res, 404, { error: "Hike not found" });
      return;
    }
    sendJson(res, 200, detail);
    return;
  }

  if (pathname === "/api/hikes/search") {
    const query = url.searchParams.get("q") || "";
    const regionId = url.searchParams.get("region") || "europe";
    const limit = Number(url.searchParams.get("limit") || 12);
    sendJson(res, 200, {
      results: searchHikes(db, regionId, query, Number.isNaN(limit) ? 12 : limit),
    });
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}
