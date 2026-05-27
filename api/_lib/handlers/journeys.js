/**
 * Shared journey codes handler.
 *
 * Endpoints:
 *   POST /api/journeys/create                   { title, ... }   -> { code, url, journey }
 *   GET  /api/journeys/code/:code                                -> stored record
 *   GET  /api/journeys/code/:code/geojson                        -> synthesized geometry
 *
 * Storage strategy:
 *   - Production (Vercel): Upstash Redis (provisioned via the Vercel Marketplace
 *     Redis integration). Keys are `journey:<CODE>`. New mints are written to
 *     Redis. Reads check Redis first, then fall back to disk so the original
 *     shipped codes keep working.
 *   - Local dev: JSON files under `Trip/shared-journeys/` (the existing
 *     behaviour). Activated automatically when no Redis credentials are set.
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { sendJson } from "../sql-shared.js";
import { PATHS } from "../paths.js";

const SHARED_DIR = PATHS.sharedJourneys;
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const CODE_LENGTH = 7;
const MAX_TITLE_LEN = 120;
const MAX_DESCRIPTION_LEN = 400;
const MAX_HIGHLIGHTS = 8;
const MAX_STOPS = 32;
const KV_KEY_PREFIX = "journey:";

function redisUrl() {
  return process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL || "";
}
function redisToken() {
  return process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN || "";
}
function isKvAvailable() {
  return Boolean(redisUrl() && redisToken());
}

let kvClient = null;
async function getKv() {
  if (kvClient) return kvClient;
  const { Redis } = await import("@upstash/redis");
  kvClient = new Redis({ url: redisUrl(), token: redisToken() });
  return kvClient;
}

function ensureDir() {
  if (!fs.existsSync(SHARED_DIR)) fs.mkdirSync(SHARED_DIR, { recursive: true });
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf-8");
      if (!raw) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

async function codeExists(code) {
  if (isKvAvailable()) {
    try {
      const kv = await getKv();
      const exists = await kv.exists(`${KV_KEY_PREFIX}${code}`);
      if (exists) return true;
    } catch (err) {
      console.warn("[journeys] KV exists check failed:", err?.message || err);
    }
  }
  return fs.existsSync(path.join(SHARED_DIR, `${code}.json`));
}

async function generateUniqueCode() {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const bytes = crypto.randomBytes(CODE_LENGTH);
    let code = "";
    for (let i = 0; i < CODE_LENGTH; i += 1) {
      code += CODE_ALPHABET[bytes[i] % CODE_ALPHABET.length];
    }
    if (!(await codeExists(code))) return code;
  }
  throw new Error("Could not allocate a unique journey code, please retry.");
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function sanitizeString(value, maxLen) {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, maxLen);
}

function sanitizeStop(stop, index) {
  if (!stop || typeof stop !== "object") return null;
  const lat = Number(stop.lat);
  const lng = Number(stop.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (lat < -85 || lat > 85 || lng < -180 || lng > 180) return null;
  const allowedKinds = new Set(["city", "park", "hike", "poi", "stop"]);
  const allowedModes = new Set(["drive", "train", "ferry", "fly", "hike"]);
  const allowedStopTypes = new Set(["start", "city", "park", "heritage", "end"]);
  const kind = allowedKinds.has(stop.kind) ? stop.kind : "stop";
  const mode = allowedModes.has(stop.mode) ? stop.mode : "drive";
  const stopType = allowedStopTypes.has(stop.stopType)
    ? stop.stopType
    : index === 0
      ? "start"
      : "city";
  return {
    id: sanitizeString(stop.id, 80) || `stop-${index + 1}`,
    name: sanitizeString(stop.name, 120) || `Stop ${index + 1}`,
    country: sanitizeString(stop.country, 80),
    kind,
    mode,
    stopType,
    day: sanitizeString(String(stop.day || ""), 12),
    tagline: sanitizeString(stop.tagline, 160),
    lat,
    lng,
  };
}

function sanitizeJourney(input) {
  const title = sanitizeString(input?.title, MAX_TITLE_LEN);
  if (!title) throw new Error("title is required");
  const stopsRaw = Array.isArray(input?.stops) ? input.stops.slice(0, MAX_STOPS) : [];
  const stops = stopsRaw.map((stop, index) => sanitizeStop(stop, index)).filter(Boolean);
  if (stops.length < 2) {
    throw new Error("A journey needs at least 2 stops with coordinates");
  }
  stops[stops.length - 1].stopType = "end";
  const highlights = Array.isArray(input?.highlights)
    ? input.highlights
        .slice(0, MAX_HIGHLIGHTS)
        .map((line) => sanitizeString(line, 200))
        .filter(Boolean)
    : [];
  return {
    schemaVersion: 1,
    title,
    description: sanitizeString(input?.description, MAX_DESCRIPTION_LEN),
    region: sanitizeString(input?.region, 120),
    continent: sanitizeString(input?.continent, 40) || "europe",
    emoji: sanitizeString(input?.emoji, 6) || "🧭",
    days: clamp(Number(input?.days) || stops.length, 1, 90),
    highlights,
    author: sanitizeString(input?.author, 60),
    stops,
  };
}

function approximateDistanceKm(stops) {
  let total = 0;
  for (let i = 1; i < stops.length; i += 1) {
    const a = stops[i - 1];
    const b = stops[i];
    const toRad = (d) => (d * Math.PI) / 180;
    const R = 6371;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const lat1 = toRad(a.lat);
    const lat2 = toRad(b.lat);
    const h =
      Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
    total += 2 * R * Math.asin(Math.sqrt(h));
  }
  return Math.round(total);
}

function buildGeojson(journey) {
  const stops = journey.stops || [];
  if (stops.length < 2) return { type: "FeatureCollection", features: [] };
  // Each leg from stops[i-1] -> stops[i] is travelled in stops[i].mode. Group
  // consecutive same-mode legs into one LineString, sharing boundary stops so
  // adjacent segments meet exactly. Mode transitions break the segment AT the
  // shared stop (not after it) so each leg is attributed to its own mode.
  const segments = [];
  let i = 0;
  while (i < stops.length - 1) {
    const legMode = stops[i + 1].mode || "drive";
    const coords = [[stops[i].lng, stops[i].lat]];
    while (i < stops.length - 1 && (stops[i + 1].mode || "drive") === legMode) {
      i += 1;
      coords.push([stops[i].lng, stops[i].lat]);
    }
    segments.push({
      type: "Feature",
      properties: { name: `${journey.title} — ${legMode}`, mode: legMode },
      geometry: { type: "LineString", coordinates: coords },
    });
  }
  const points = stops.map((stop) => ({
    type: "Feature",
    properties: {
      name: stop.name,
      country: stop.country,
      day: stop.day,
      stopType: stop.stopType,
      kind: stop.kind,
      tagline: stop.tagline,
    },
    geometry: { type: "Point", coordinates: [stop.lng, stop.lat] },
  }));
  return { type: "FeatureCollection", features: [...segments, ...points] };
}

async function readStored(code) {
  if (isKvAvailable()) {
    try {
      const kv = await getKv();
      const fromKv = await kv.get(`${KV_KEY_PREFIX}${code}`);
      if (fromKv) {
        return typeof fromKv === "string" ? JSON.parse(fromKv) : fromKv;
      }
    } catch (err) {
      console.warn("[journeys] KV read failed, falling back to disk:", err?.message || err);
    }
  }
  const file = path.join(SHARED_DIR, `${code}.json`);
  if (!fs.existsSync(file)) return null;
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (err) {
    console.warn(`[journeys] corrupt file ${file}: ${err?.message || err}`);
    return null;
  }
}

const JOURNEY_TTL_SEC = 60 * 60 * 24 * 365; // 1 year

async function writeStored(code, record) {
  if (isKvAvailable()) {
    const kv = await getKv();
    await kv.set(`${KV_KEY_PREFIX}${code}`, record, { ex: JOURNEY_TTL_SEC });
    return;
  }
  if (process.env.VERCEL) {
    throw new Error(
      "Shared journey storage is not configured. Add Upstash Redis (KV_REST_API_URL and KV_REST_API_TOKEN) in your Vercel project environment variables."
    );
  }
  ensureDir();
  fs.writeFileSync(
    path.join(SHARED_DIR, `${code}.json`),
    JSON.stringify(record, null, 2),
    "utf-8"
  );
}

/**
 * Vercel rewrites `/api/journeys/*` → `/api/journeys?path=*` so the function
 * receives the subpath in a query param; dev passes the full pathname as-is.
 */
function resolveJourneysPathname(req, url) {
  const pathParam = url.searchParams.get("path");
  if (pathParam) {
    const segment = String(pathParam).replace(/^\/+|\/+$/g, "");
    if (segment) {
      return `/api/journeys/${segment}`;
    }
  }
  const forwarded =
    req.headers["x-vercel-original-path"] ||
    req.headers["x-invoke-path"] ||
    req.headers["x-forwarded-uri"];
  if (forwarded) {
    const raw = String(forwarded).split("?")[0];
    if (raw.startsWith("/api/journeys")) {
      return raw;
    }
  }
  return url.pathname;
}

export async function handleJourneys(req, res, url) {
  const pathname = resolveJourneysPathname(req, url);
  res.setHeader("Cache-Control", "no-store");

  if (pathname === "/api/journeys/status" && req.method === "GET") {
    const kv = isKvAvailable();
    sendJson(res, 200, {
      storage: kv ? "redis" : process.env.VERCEL ? "unavailable" : "disk",
      crossDeviceCodes: kv,
    });
    return;
  }

  if (pathname === "/api/journeys/create" && req.method === "POST") {
    try {
      const body = await readBody(req);
      const journey = sanitizeJourney(body);
      const code = await generateUniqueCode();
      const record = {
        ...journey,
        code,
        createdAt: new Date().toISOString(),
        distanceKm: approximateDistanceKm(journey.stops),
      };
      await writeStored(code, record);
      sendJson(res, 201, {
        code,
        url: `/?journey=${code}`,
        journey: record,
        storage: isKvAvailable() ? "redis" : "disk",
        crossDeviceCodes: isKvAvailable() || !process.env.VERCEL,
      });
    } catch (err) {
      sendJson(res, 400, { error: err.message || "Invalid journey" });
    }
    return;
  }

  const detailMatch = pathname.match(/^\/api\/journeys\/code\/([A-Z0-9]+)$/);
  if (detailMatch && req.method === "GET") {
    const code = detailMatch[1].toUpperCase();
    const record = await readStored(code);
    if (!record) {
      sendJson(res, 404, { error: "Journey not found" });
      return;
    }
    sendJson(res, 200, record);
    return;
  }

  const geoMatch = pathname.match(/^\/api\/journeys\/code\/([A-Z0-9]+)\/geojson$/);
  if (geoMatch && req.method === "GET") {
    const code = geoMatch[1].toUpperCase();
    const record = await readStored(code);
    if (!record) {
      sendJson(res, 404, { error: "Journey not found" });
      return;
    }
    sendJson(res, 200, buildGeojson(record));
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}
