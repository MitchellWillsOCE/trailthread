/**
 * Country Dossier API.
 *
 * GET /api/country/:cc
 *   -> {
 *        cc, country, region, bounds,
 *        counts: { cities, parks, hikes, pois },
 *        highlights: { cities: [...], parks: [...], hikes: [...], pois: [...] },
 *        season: { peak, shoulder, low, note }
 *      }
 *
 * Reads from the same SQLite databases used by cities-api / parks-api /
 * hikes-api / poi-api, joined by `cc`.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SQL_DIST = path.join(ROOT, "node_modules", "sql.js", "dist");
const DB_PATHS = {
  cities: path.join(ROOT, "Trip", "cities", "cities.db"),
  parks: path.join(ROOT, "Trip", "parks", "parks.db"),
  hikes: path.join(ROOT, "Trip", "hikes", "hikes.db"),
  pois: path.join(ROOT, "Trip", "poi", "poi.db"),
};

const SEASON_HINTS_PATH = path.join(ROOT, "scripts", "data", "country-seasons.json");

function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

function parseJsonField(value, fallback = []) {
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value === "string" && value) {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

function sqlAll(db, sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params.length ? params : []);
  const rows = [];
  while (stmt.step()) {
    rows.push(stmt.getAsObject());
  }
  stmt.free();
  return rows;
}

function sqlGet(db, sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params.length ? params : []);
  const row = stmt.step() ? stmt.getAsObject() : null;
  stmt.free();
  return row;
}

function safeLoadSeasonHints() {
  try {
    return JSON.parse(fs.readFileSync(SEASON_HINTS_PATH, "utf-8"));
  } catch {
    return { default: null, byCountry: {} };
  }
}

function loadDb(SQL, file) {
  if (!fs.existsSync(file)) {
    return null;
  }
  const buf = fs.readFileSync(file);
  return new SQL.Database(new Uint8Array(buf));
}

export function countryDossierApiPlugin() {
  let dbs = null;
  let loadPromise = null;
  let seasonHints = safeLoadSeasonHints();
  fs.watchFile(SEASON_HINTS_PATH, { interval: 5000 }, () => {
    seasonHints = safeLoadSeasonHints();
  });

  async function ensureDbs() {
    if (dbs) {
      return dbs;
    }
    if (loadPromise) {
      return loadPromise;
    }
    loadPromise = (async () => {
      const initSqlJs = (await import("sql.js")).default;
      const SQL = await initSqlJs({
        locateFile: (file) => path.join(SQL_DIST, file),
      });
      const out = {};
      for (const [key, file] of Object.entries(DB_PATHS)) {
        out[key] = loadDb(SQL, file);
      }
      dbs = out;
      console.info("[country-dossier-api] DBs ready.");
      return dbs;
    })().catch((err) => {
      loadPromise = null;
      throw err;
    });
    return loadPromise;
  }

  function topCities(db, cc) {
    if (!db) {
      return [];
    }
    const rows = sqlAll(
      db,
      `SELECT id, name, country, lat, lng, pop, tier, tagline, photos_json
         FROM cities
         WHERE cc = ?
         ORDER BY CASE tier WHEN 'major' THEN 0 WHEN 'regional' THEN 1 ELSE 2 END,
                  COALESCE(pop, 0) DESC
         LIMIT 6`,
      [cc.toUpperCase()]
    );
    return rows.map((row) => ({
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
    if (!db) {
      return [];
    }
    const rows = sqlAll(
      db,
      `SELECT id, name, country, lat, lng, tier, biodiversity, area_km2, tagline, photos_json, stay
         FROM parks
         WHERE cc = ?
         ORDER BY popularity DESC
         LIMIT 6`,
      [cc.toLowerCase()]
    );
    return rows.map((row) => ({
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
    if (!db) {
      return [];
    }
    const rows = sqlAll(
      db,
      `SELECT id, name, country, lat, lng, length_km, difficulty, tier, tagline, photos_json
         FROM hikes
         WHERE cc = ?
         ORDER BY CASE tier WHEN 'major' THEN 0 WHEN 'regional' THEN 1 ELSE 2 END,
                  popularity DESC,
                  COALESCE(length_km, 0) DESC
         LIMIT 6`,
      [cc.toLowerCase()]
    );
    return rows.map((row) => ({
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
    if (!db) {
      return [];
    }
    const rows = sqlAll(
      db,
      `SELECT id, name, country, lat, lng, tier, category, tagline, photos_json
         FROM pois
         WHERE cc = ?
         ORDER BY popularity DESC
         LIMIT 6`,
      [cc.toLowerCase()]
    );
    return rows.map((row) => ({
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
    if (!citiesDb) {
      return { country: null, bounds: null };
    }
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
    if (!row) {
      return { country: null, bounds: null };
    }
    return {
      country: row.country,
      bounds: { west: row.west, south: row.south, east: row.east, north: row.north },
    };
  }

  function counts(databases, cc) {
    const fromCount = (db, table, ccCase) => {
      if (!db) {
        return 0;
      }
      const r = sqlGet(db, `SELECT COUNT(*) AS c FROM ${table} WHERE cc = ?`, [ccCase]);
      return r?.c || 0;
    };
    return {
      cities: fromCount(databases.cities, "cities", cc.toUpperCase()),
      parks: fromCount(databases.parks, "parks", cc.toLowerCase()),
      hikes: fromCount(databases.hikes, "hikes", cc.toLowerCase()),
      pois: fromCount(databases.pois, "pois", cc.toLowerCase()),
    };
  }

  function resolveSeasonHint(countryName) {
    if (!countryName) {
      return seasonHints.default || null;
    }
    const direct = seasonHints.byCountry?.[countryName];
    if (direct) {
      return direct;
    }
    return seasonHints.default || null;
  }

  async function handle(req, res) {
    const url = new URL(req.url, "http://localhost");
    const match = url.pathname.match(/^\/api\/country\/([A-Za-z]{2})$/);
    if (!match) {
      sendJson(res, 404, { error: "Not found" });
      return;
    }
    if (req.method !== "GET") {
      sendJson(res, 405, { error: "Method not allowed" });
      return;
    }
    const cc = match[1].toLowerCase();
    let databases;
    try {
      databases = await ensureDbs();
    } catch (err) {
      sendJson(res, 503, { error: err.message || "DB unavailable" });
      return;
    }

    const header = countryHeader(databases.cities, cc);
    const dossier = {
      cc,
      country: header.country,
      bounds: header.bounds,
      counts: counts(databases, cc),
      highlights: {
        cities: topCities(databases.cities, cc),
        parks: topParks(databases.parks, cc),
        hikes: topHikes(databases.hikes, cc),
        pois: topPois(databases.pois, cc),
      },
      season: resolveSeasonHint(header.country),
    };
    if (!dossier.country && dossier.counts.cities === 0 && dossier.counts.parks === 0) {
      sendJson(res, 404, { error: "Country not in catalog" });
      return;
    }
    sendJson(res, 200, dossier);
  }

  const attach = (server) => {
    server.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/api/country/")) {
        next();
        return;
      }
      try {
        await handle(req, res);
      } catch (err) {
        console.error("[country-dossier-api]", err);
        sendJson(res, 500, { error: err.message || "Server error" });
      }
    });
  };

  return {
    name: "country-dossier-api",
    configureServer(server) {
      attach(server);
    },
    configurePreviewServer(server) {
      attach(server);
    },
  };
}
