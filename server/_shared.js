/**
 * Shared helpers for the catalog API plugins (cities / parks / hikes / poi).
 *
 * Centralises:
 *  - JSON response helper
 *  - sql.js binding helpers (sqlAll / sqlGet)
 *  - parseJsonField for `*_json` columns
 *  - tiersForZoom factory (each catalog has its own thresholds and tier names)
 *  - sql.js Database loader with single-flight, cached instance
 *  - manifest reader
 *  - middleware helper that wraps a request handler with a `db` argument
 */
import fs from "node:fs";
import path from "node:path";

export function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

export function sqlAll(db, sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params.length ? params : []);
  const rows = [];
  while (stmt.step()) {
    rows.push(stmt.getAsObject());
  }
  stmt.free();
  return rows;
}

export function sqlGet(db, sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params.length ? params : []);
  const row = stmt.step() ? stmt.getAsObject() : null;
  stmt.free();
  return row;
}

export function parseJsonField(value, fallback = []) {
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

/**
 * Build a `tiersForZoom(zoom)` function tuned to a particular catalog.
 * `thresholds` is `[majorOnlyMax, majorRegionalMax]` and `bottom` is the tier name
 * used at high zoom (e.g. "local" for parks/poi/hikes, "town" for cities).
 */
export function makeTiersForZoom({ thresholds = [5, 7], bottom = "local" } = {}) {
  const [zMajor, zRegional] = thresholds;
  return function tiersForZoom(zoom) {
    const z = Number(zoom) || 8;
    if (z <= zMajor) {
      return ["major"];
    }
    if (z <= zRegional) {
      return ["major", "regional"];
    }
    return ["major", "regional", bottom];
  };
}

/**
 * Read a manifest file safely. Returns null if missing or malformed.
 */
export function readManifestSafe(manifestPath) {
  try {
    if (!fs.existsSync(manifestPath)) {
      return null;
    }
    return JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
  } catch {
    return null;
  }
}

/**
 * Build an `ensureSqlDatabase()` loader with single-flight semantics.
 *
 * Returns the live `Database` instance once loaded, throwing if the file
 * is missing or the WASM runtime cannot start. Callers must catch errors.
 */
export function createSqlDatabaseLoader({ dbPath, sqlDistDir, logTag, missingMessage }) {
  let db = null;
  let loadPromise = null;
  return async function ensureSqlDatabase() {
    if (db) return db;
    if (loadPromise) return loadPromise;
    loadPromise = (async () => {
      if (!fs.existsSync(dbPath)) {
        throw new Error(missingMessage || `Database not found at ${dbPath}`);
      }
      const initSqlJs = (await import("sql.js")).default;
      const SQL = await initSqlJs({
        locateFile: (file) => path.join(sqlDistDir, file),
      });
      const buf = fs.readFileSync(dbPath);
      db = new SQL.Database(new Uint8Array(buf));
      if (logTag) {
        console.info(`[${logTag}] SQLite loaded via sql.js (${buf.length} B).`);
      }
      return db;
    })().catch((err) => {
      loadPromise = null;
      throw err;
    });
    return loadPromise;
  };
}

/**
 * Wrap a per-request handler with the boilerplate every catalog API repeats:
 *   - filter requests by URL prefix
 *   - ensure the SQLite DB is loaded (respond 503 if not)
 *   - normalise unhandled errors into a 500 response
 *
 * The wrapped handler receives (req, res, db, url).
 */
export function createCatalogMiddleware({
  urlPrefix,
  ensureSqlDatabase,
  handle,
  logTag,
  dbUnavailableMessage,
}) {
  return (server) => {
    server.middlewares.use((req, res, next) => {
      if (!req.url?.startsWith(urlPrefix)) {
        next();
        return;
      }
      (async () => {
        let db = null;
        try {
          db = await ensureSqlDatabase();
        } catch (error) {
          console.warn(`[${logTag}]`, error?.message || error);
          sendJson(res, 503, { error: dbUnavailableMessage || "Database not available" });
          return;
        }
        const url = new URL(req.url, "http://localhost");
        await handle(req, res, db, url);
      })().catch((err) => {
        console.error(`[${logTag}]`, err);
        sendJson(res, 500, { error: "Internal error" });
      });
    });
  };
}
