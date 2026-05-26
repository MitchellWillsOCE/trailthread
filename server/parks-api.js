import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveSqlitePath } from "./resolve-sqlite-db.js";
import {
  createCatalogMiddleware,
  createSqlDatabaseLoader,
  makeTiersForZoom,
  parseJsonField,
  readManifestSafe,
  sendJson,
  sqlAll,
  sqlGet,
} from "./_shared.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DB_PATH = resolveSqlitePath(path.join(ROOT, "Trip", "parks", "parks.db"));
const MANIFEST_PATH = path.join(ROOT, "Trip", "parks", "manifest.json");
const SQL_DIST = path.join(ROOT, "node_modules", "sql.js", "dist");

const tiersForZoom = makeTiersForZoom({ thresholds: [5, 7], bottom: "local" });

function formatArea(km2) {
  const n = Number(km2) || 0;
  if (n >= 1000) {
    return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k km²`;
  }
  return `${Math.round(n)} km²`;
}

function rowToDetail(row) {
  return {
    kind: "park",
    id: row.id,
    name: row.name,
    country: row.country,
    cc: row.cc,
    lat: row.lat,
    lng: row.lng,
    area_km2: row.area_km2,
    area_label: formatArea(row.area_km2),
    biodiversity: row.biodiversity,
    popularity: row.popularity,
    tier: row.tier,
    category: row.category || "national-park",
    summary: row.summary,
    general: row.summary,
    tagline: row.tagline,
    stay: row.stay,
    activities: parseJsonField(row.activities_json),
    tips: parseJsonField(row.tips_json),
    photos: parseJsonField(row.photos_json),
    highlights: parseJsonField(row.highlights_json),
    iucn_category: row.iucn_category,
    source: row.source,
    enriched: row.enriched ?? 0,
    isMajorCard: row.tier === "major",
  };
}

function queryFeatures(db, regionId, west, south, east, north, zoom, countryCc) {
  const tiers = tiersForZoom(zoom);
  const placeholders = tiers.map(() => "?").join(", ");
  const countryClause = countryCc ? " AND cc = ?" : "";
  const sql = `
    SELECT id, name, country, cc, lat, lng, area_km2, biodiversity, popularity, tier, category, tagline
    FROM parks
    WHERE region_id = ?
      AND lat >= ? AND lat <= ?
      AND lng >= ? AND lng <= ?
      AND tier IN (${placeholders})${countryClause}
    ORDER BY popularity DESC
    LIMIT 350
  `;
  const params = [regionId, south, north, west, east, ...tiers];
  if (countryCc) params.push(countryCc);
  return sqlAll(db, sql, params).map((row) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [row.lng, row.lat] },
    properties: {
      id: row.id,
      name: row.name,
      country: row.country,
      cc: row.cc,
      area_km2: row.area_km2,
      biodiversity: row.biodiversity,
      popularity: row.popularity,
      tier: row.tier,
      category: row.category || "national-park",
      tagline: row.tagline,
    },
  }));
}

function searchParks(db, regionId, query, limit = 12) {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  const like = `%${q}%`;
  const prefix = `${q}%`;
  const sql = `
    SELECT id, name, country, cc, lat, lng, area_km2, biodiversity, popularity, tier, category, tagline
    FROM parks
    WHERE region_id = ?
      AND (lower(name) LIKE ? OR lower(country) LIKE ?)
    ORDER BY
      CASE WHEN lower(name) = ? THEN 0 WHEN lower(name) LIKE ? THEN 1 ELSE 2 END,
      popularity DESC
    LIMIT ?
  `;
  return sqlAll(db, sql, [regionId, like, like, q, prefix, limit]);
}

export function parksApiPlugin() {
  const ensureSqlDatabase = createSqlDatabaseLoader({
    dbPath: DB_PATH,
    sqlDistDir: SQL_DIST,
    logTag: "parks-api",
    missingMessage: `Park database not found at ${DB_PATH}. Run: npm run build:parks`,
  });

  async function handle(req, res, db, url) {
    if (req.method !== "GET") {
      sendJson(res, 405, { error: "Method not allowed" });
      return;
    }
    const pathname = url.pathname;

    if (pathname === "/api/parks/manifest") {
      const manifest = readManifestSafe(MANIFEST_PATH);
      if (!manifest) {
        sendJson(res, 503, { error: "Manifest not available" });
        return;
      }
      sendJson(res, 200, manifest);
      return;
    }

    const featuresMatch = pathname.match(/^\/api\/parks\/([^/]+)\/features$/);
    if (featuresMatch) {
      const regionId = featuresMatch[1];
      const west = Number(url.searchParams.get("west"));
      const south = Number(url.searchParams.get("south"));
      const east = Number(url.searchParams.get("east"));
      const north = Number(url.searchParams.get("north"));
      const zoom = Number(url.searchParams.get("zoom") || 8);
      const countryCc = (url.searchParams.get("country") || "").trim().toUpperCase() || null;
      if ([west, south, east, north].some((n) => Number.isNaN(n))) {
        sendJson(res, 400, { error: "Bounds required" });
        return;
      }
      sendJson(res, 200, {
        type: "FeatureCollection",
        features: queryFeatures(db, regionId, west, south, east, north, zoom, countryCc),
      });
      return;
    }

    const detailMatch = pathname.match(/^\/api\/parks\/detail\/([^/]+)$/);
    if (detailMatch) {
      const parkId = decodeURIComponent(detailMatch[1]);
      const row = sqlGet(db, "SELECT * FROM parks WHERE id = ?", [parkId]);
      if (!row) {
        sendJson(res, 404, { error: "Park not found" });
        return;
      }
      sendJson(res, 200, rowToDetail(row));
      return;
    }

    if (pathname === "/api/parks/search") {
      const query = url.searchParams.get("q") || "";
      const regionId = url.searchParams.get("region") || "europe";
      const limit = Number(url.searchParams.get("limit") || 10);
      sendJson(res, 200, { results: searchParks(db, regionId, query, limit) });
      return;
    }

    sendJson(res, 404, { error: "Not found" });
  }

  return {
    name: "parks-api",
    configureServer: createCatalogMiddleware({
      urlPrefix: "/api/parks",
      ensureSqlDatabase,
      handle,
      logTag: "parks-api",
      dbUnavailableMessage: "Park database not available",
    }),
  };
}
