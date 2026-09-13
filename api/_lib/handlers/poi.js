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

const tiersForZoom = makeTiersForZoom({ thresholds: [6, 8], bottom: "local" });

const ensureSqlDatabase = createSqlDatabaseLoader({
  dbPath: PATHS.poiDb,
  logTag: "poi-api",
  missingMessage: `POI database not found at ${PATHS.poiDb}. Run: npm run build:poi`,
});

const CATEGORY_LABELS = {
  fortress: "Fortress",
  mountain: "Mountain",
  monument: "Monument",
  heritage: "Heritage site",
  landmark: "Landmark",
};

function rowToDetail(row) {
  const category = row.category || "heritage";
  return {
    kind: "poi",
    id: row.id,
    name: row.name,
    country: row.country,
    cc: row.cc,
    lat: row.lat,
    lng: row.lng,
    category,
    category_label: CATEGORY_LABELS[category] || "Point of interest",
    popularity: row.popularity,
    tier: row.tier,
    summary: row.summary,
    general: row.summary,
    tagline: row.tagline,
    activities: parseJsonField(row.activities_json),
    tips: parseJsonField(row.tips_json),
    photos: parseJsonField(row.photos_json),
    highlights: parseJsonField(row.highlights_json),
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
    SELECT id, name, country, cc, category, lat, lng, popularity, tier, tagline
    FROM pois
    WHERE region_id = ?
      AND lat >= ? AND lat <= ?
      AND lng >= ? AND lng <= ?
      AND tier IN (${placeholders})${countryClause}
    ORDER BY popularity DESC
    LIMIT 400
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
      category: row.category,
      popularity: row.popularity,
      tier: row.tier,
      tagline: row.tagline,
    },
  }));
}

function searchPois(db, regionId, query, limit = 12) {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  const like = `%${q}%`;
  const prefix = `${q}%`;
  return sqlAll(
    db,
    `SELECT id, name, country, cc, category, lat, lng, popularity, tier, tagline
       FROM pois
       WHERE region_id = ?
         AND (lower(name) LIKE ? OR lower(country) LIKE ? OR lower(category) LIKE ?)
       ORDER BY
         CASE WHEN lower(name) = ? THEN 0 WHEN lower(name) LIKE ? THEN 1 ELSE 2 END,
         popularity DESC
       LIMIT ?`,
    [regionId, like, like, like, q, prefix, limit]
  );
}

export async function handlePoi(req, res, url) {
  if (req.method !== "GET") {
    sendJson(res, 405, { error: "Method not allowed" });
    return;
  }
  const pathname = url.pathname;

  if (pathname === "/api/poi/manifest") {
    const manifest = readManifestSafe(PATHS.poiManifest);
    if (!manifest) {
      sendJson(res, 503, { error: "Manifest not available" });
      return;
    }
    sendJson(res, 200, manifest);
    return;
  }

  let db;
  try {
    db = await ensureSqlDatabase();
  } catch (error) {
    console.warn("[poi-api]", error?.message || error);
    sendJson(res, 503, { error: "POI database not available" });
    return;
  }

  const featuresMatch = pathname.match(/^\/api\/poi\/([^/]+)\/features$/);
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

  const detailMatch = pathname.match(/^\/api\/poi\/detail\/([^/]+)$/);
  if (detailMatch) {
    const row = sqlGet(db, "SELECT * FROM pois WHERE id = ?", [decodeURIComponent(detailMatch[1])]);
    if (!row) {
      sendJson(res, 404, { error: "POI not found" });
      return;
    }
    sendJson(res, 200, rowToDetail(row));
    return;
  }

  if (pathname === "/api/poi/search") {
    const query = url.searchParams.get("q") || "";
    const regionId = url.searchParams.get("region") || "europe";
    const limit = Number(url.searchParams.get("limit") || 10);
    sendJson(res, 200, { results: searchPois(db, regionId, query, limit) });
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}
