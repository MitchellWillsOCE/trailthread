import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  makeTiersForZoom,
  parseJsonField,
  readManifestSafe,
  sendJson,
  sqlAll,
  sqlGet,
} from "./_shared.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DB_PATH = path.join(ROOT, "Trip", "hikes", "hikes.db");
const MANIFEST_PATH = path.join(ROOT, "Trip", "hikes", "manifest.json");
const SQL_DIST = path.join(ROOT, "node_modules", "sql.js", "dist");

const tiersForZoom = makeTiersForZoom({ thresholds: [6, 8], bottom: "local" });

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
    Array.isArray(parsed.coordinates)
  ) {
    if (parsed.type === "LineString" || parsed.type === "MultiLineString") {
      return parsed;
    }
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
    row.start_lat !== null && row.start_lat !== undefined &&
    row.start_lng !== null && row.start_lng !== undefined
      ? {
          lat: row.start_lat,
          lng: row.start_lng,
          name: row.start_name || null
        }
      : null;
  const end =
    row.end_lat !== null && row.end_lat !== undefined &&
    row.end_lng !== null && row.end_lng !== undefined
      ? {
          lat: row.end_lat,
          lng: row.end_lng,
          name: row.end_name || null
        }
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
    start_instructions: row.start_instructions || null
  };
}

const readManifest = () => readManifestSafe(MANIFEST_PATH);

export function hikesApiPlugin() {
  let sqlDb = null;
  let sqlDbMtime = 0;
  let loadPromise = null;
  const geojsonCache = new Map();

  function dbMtimeMs() {
    try {
      return fs.statSync(DB_PATH).mtimeMs;
    } catch {
      return 0;
    }
  }

  async function ensureSqlDatabase() {
    const currentMtime = dbMtimeMs();
    if (sqlDb && currentMtime === sqlDbMtime) {
      return sqlDb;
    }
    if (loadPromise) {
      return loadPromise;
    }

    loadPromise = (async () => {
      if (!fs.existsSync(DB_PATH)) {
        throw new Error(`Hike database not found at ${DB_PATH}. Run: npm run build:hikes`);
      }
      if (!fs.existsSync(path.join(SQL_DIST, "sql-wasm.wasm"))) {
        throw new Error("sql.js WASM not found. Run: npm install");
      }
      const initSqlJs = (await import("sql.js")).default;
      const SQL = await initSqlJs({
        locateFile: (file) => path.join(SQL_DIST, file)
      });
      const buf = fs.readFileSync(DB_PATH);
      if (sqlDb) {
        try { sqlDb.close(); } catch {}
      }
      sqlDb = new SQL.Database(new Uint8Array(buf));
      sqlDbMtime = currentMtime || dbMtimeMs();
      geojsonCache.clear();
      console.info("[hikes-api] SQLite loaded via sql.js.");
      return sqlDb;
    })().catch((err) => {
      loadPromise = null;
      throw err;
    }).finally(() => {
      loadPromise = null;
    });

    return loadPromise;
  }

  const resolveGeojsonPath = (regionId) => {
    const manifest = readManifest();
    const region = manifest?.regions?.find((item) => item.id === regionId);
    const legacy = region?.legacyGeojson;
    if (!legacy) {
      return null;
    }
    return path.resolve(ROOT, legacy.replace(/^\.\//, ""));
  };

  const loadGeojsonFeatures = (regionId) => {
    if (geojsonCache.has(regionId)) {
      return geojsonCache.get(regionId);
    }
    const geoPath = resolveGeojsonPath(regionId);
    if (!geoPath || !fs.existsSync(geoPath)) {
      geojsonCache.set(regionId, []);
      return [];
    }
    const collection = JSON.parse(fs.readFileSync(geoPath, "utf-8"));
    const features = collection.features || [];
    geojsonCache.set(regionId, features);
    return features;
  };

  const queryFeaturesSql = (db, regionId, west, south, east, north, zoom, countryCc) => {
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
    if (countryCc) {
      params.push(countryCc);
    }
    return sqlAll(db, sql, params);
  };

  const queryFeaturesGeojson = (regionId, west, south, east, north, zoom, countryCc) => {
    const tiers = new Set(tiersForZoom(zoom));
    return loadGeojsonFeatures(regionId)
      .filter((feature) => {
        const props = feature.properties || {};
        if (!tiers.has(props.tier)) {
          return false;
        }
        if (countryCc && props.cc !== countryCc) {
          return false;
        }
        const [lng, lat] = feature.geometry?.coordinates || [0, 0];
        return lat >= south && lat <= north && lng >= west && lng <= east;
      })
      .sort((a, b) => (b.properties?.popularity || 0) - (a.properties?.popularity || 0))
      .slice(0, 400);
  };

  const queryFeatures = (db, regionId, west, south, east, north, zoom, countryCc) => {
    if (!db) {
      return queryFeaturesGeojson(regionId, west, south, east, north, zoom, countryCc);
    }
    const rows = queryFeaturesSql(db, regionId, west, south, east, north, zoom, countryCc);
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
        tagline: row.tagline
      }
    }));
  };

  const getHikeDetail = (db, hikeId) => {
    if (!db) {
      const features = loadGeojsonFeatures("europe");
      const feature = features.find((f) => f.properties?.id === hikeId);
      if (!feature) {
        return null;
      }
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
        source: "OpenStreetMap"
      };
    }
    const row = sqlGet(db, "SELECT * FROM hikes WHERE id = ?", [hikeId]);
    return row ? rowToDetail(row) : null;
  };

  const searchHikes = (db, regionId, query, limit = 12) => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) {
      return [];
    }
    const like = `%${q}%`;
    const prefix = `${q}%`;
    if (!db) {
      return loadGeojsonFeatures(regionId)
        .filter((f) => {
          const name = f.properties?.name?.toLowerCase() || "";
          return name.includes(q);
        })
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
          tagline: f.properties.tagline
        }));
    }
    const sql = `
        SELECT id, name, country, cc, lat, lng, length_km, popularity, tier, tagline
        FROM hikes
        WHERE region_id = ?
          AND (lower(name) LIKE ? OR lower(country) LIKE ?)
        ORDER BY
          CASE
            WHEN lower(name) = ? THEN 0
            WHEN lower(name) LIKE ? THEN 1
            ELSE 2
          END,
          popularity DESC
        LIMIT ?
      `;
    return sqlAll(db, sql, [regionId, like, like, q, prefix, limit]);
  };

  const handleHikes = async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    const pathname = url.pathname;

    if (req.method !== "GET") {
      sendJson(res, 405, { error: "Method not allowed" });
      return;
    }

    let db = null;
    try {
      db = await ensureSqlDatabase();
    } catch (error) {
      console.warn("[hikes-api] SQLite load failed — GeoJSON-only mode.", error?.message || error);
    }

    if (pathname === "/api/hikes/manifest") {
      const manifest = readManifest();
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
        features: queryFeatures(db, regionId, west, south, east, north, zoom, countryCc)
      });
      return;
    }

    const detailMatch = pathname.match(/^\/api\/hikes\/detail\/([^/]+)$/);
    if (detailMatch) {
      const hikeId = decodeURIComponent(detailMatch[1]);
      const detail = getHikeDetail(db, hikeId);
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
      if (query.trim().length < 2) {
        sendJson(res, 200, { results: [] });
        return;
      }
      sendJson(res, 200, {
        results: searchHikes(db, regionId, query, Number.isNaN(limit) ? 12 : limit)
      });
      return;
    }

    sendJson(res, 404, { error: "Not found" });
  };

  const attach = (server) => {
    server.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/api/hikes")) {
        next();
        return;
      }
      try {
        await handleHikes(req, res);
      } catch (error) {
        console.error("[hikes-api]", error);
        sendJson(res, 500, { error: error.message || "Server error" });
      }
    });
  };

  return {
    name: "hikes-api",
    configureServer: attach,
    configurePreviewServer: attach,
    closeBundle() {
      sqlDb?.close();
      sqlDb = null;
      loadPromise = null;
    }
  };
}
