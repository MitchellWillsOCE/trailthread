/**
 * Platform-agnostic helpers shared by every catalog handler. Used by both the
 * Vite dev plugins (under `server/`) and the Vercel serverless functions
 * (under `api/`). No Vite-specific or Vercel-specific imports here.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

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
  if (Array.isArray(value)) return value;
  if (typeof value === "string" && value) {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

function decodeJsonString(raw) {
  try {
    return JSON.parse(`"${raw}"`);
  } catch {
    return raw;
  }
}

function safeHttpUrl(url) {
  const value = String(url || "").trim();
  if (!/^https?:\/\//i.test(value)) return "";
  return value;
}

/** First photo URL from a photos JSON blob, without keeping the rest of the gallery. */
export function coverUrlFromPhotos(value) {
  if (!value) return "";
  if (Array.isArray(value)) {
    const first = value[0];
    if (!first) return "";
    if (typeof first === "string") return safeHttpUrl(first);
    return safeHttpUrl(first.url || first.src || "");
  }
  if (typeof value === "object") {
    return safeHttpUrl(value.url || value.src || "");
  }
  const text = String(value);
  if (!text || text === "[]") return "";
  const match = text.match(/"(?:url|src)"\s*:\s*"((?:\\.|[^"\\])*)"/);
  if (!match) return "";
  return safeHttpUrl(decodeJsonString(match[1]));
}

const COVER_TABLES = new Set(["cities", "parks", "hikes", "pois"]);

function rowWantsCover(row) {
  const tier = String(row?.tier || "").toLowerCase();
  const category = String(row?.category || "").toLowerCase();
  return tier === "major" || tier === "regional" || category === "capital";
}

/** Cover photo for a map feature that is worth a photo pin. */
export function catalogCoverForRow(row) {
  if (!rowWantsCover(row)) return "";
  return coverUrlFromPhotos(row.photos_json || row.photos || row.cover || "");
}

/**
 * Fill `row.cover` for major and regional places. A second query keeps town
 * rows from pulling photo JSON into memory.
 */
export function attachCoverUrls(db, table, rows) {
  if (!db || !COVER_TABLES.has(table) || !Array.isArray(rows) || !rows.length) return;
  const ids = [];
  for (const row of rows) {
    if (row?.id && rowWantsCover(row)) ids.push(row.id);
  }
  if (!ids.length) return;
  const placeholders = ids.map(() => "?").join(", ");
  let covers;
  try {
    covers = sqlAll(
      db,
      `SELECT id, photos_json FROM ${table} WHERE id IN (${placeholders})`,
      ids
    );
  } catch {
    return;
  }
  const byId = new Map();
  for (const row of covers) {
    const cover = coverUrlFromPhotos(row.photos_json);
    if (cover) byId.set(row.id, cover);
  }
  for (const row of rows) {
    const cover = byId.get(row.id);
    if (cover) row.cover = cover;
  }
}

export function makeTiersForZoom({ thresholds = [5, 7], bottom = "local" } = {}) {
  const [zMajor, zRegional] = thresholds;
  return function tiersForZoom(zoom) {
    const z = Number(zoom) || 8;
    if (z <= zMajor) return ["major"];
    if (z <= zRegional) return ["major", "regional"];
    return ["major", "regional", bottom];
  };
}

export function readManifestSafe(manifestPath) {
  try {
    if (!fs.existsSync(manifestPath)) return null;
    return JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
  } catch {
    return null;
  }
}

let cachedSqlJs = null;
let cachedSqlJsPromise = null;

/**
 * Initialize sql.js exactly once per process. Resolves the WASM file via
 * Node's module resolver (which is traceable by Vercel's bundler) so the
 * same code path works in `vite dev` and in a deployed serverless function.
 */
export function ensureSqlJs() {
  if (cachedSqlJs) return Promise.resolve(cachedSqlJs);
  if (cachedSqlJsPromise) return cachedSqlJsPromise;
  cachedSqlJsPromise = (async () => {
    const initSqlJs = (await import("sql.js")).default;
    const wasmPath = require.resolve("sql.js/dist/sql-wasm.wasm");
    const wasmDir = path.dirname(wasmPath);
    cachedSqlJs = await initSqlJs({
      locateFile: (file) => path.join(wasmDir, file),
    });
    return cachedSqlJs;
  })().catch((err) => {
    cachedSqlJsPromise = null;
    throw err;
  });
  return cachedSqlJsPromise;
}

/**
 * Build a single-flight, cached SQLite loader for one catalog DB. Returns a
 * Database instance (or throws if the file is missing). Module-level state
 * is fine for both Vite dev (one Node process) and Vercel functions (warm
 * container persistence).
 */
export function createSqlDatabaseLoader({ dbPath, logTag, missingMessage }) {
  let db = null;
  let loadPromise = null;
  return async function ensureSqlDatabase() {
    if (db) return db;
    if (loadPromise) return loadPromise;
    loadPromise = (async () => {
      if (!fs.existsSync(dbPath)) {
        throw new Error(missingMessage || `Database not found at ${dbPath}`);
      }
      const SQL = await ensureSqlJs();
      const buf = fs.readFileSync(dbPath);
      db = new SQL.Database(new Uint8Array(buf));
      if (logTag) {
        console.info(`[${logTag}] SQLite loaded (${buf.length} B).`);
      }
      return db;
    })().catch((err) => {
      loadPromise = null;
      throw err;
    });
    return loadPromise;
  };
}
