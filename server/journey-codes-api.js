/**
 * Shared journey codes API.
 *
 * Endpoints:
 *   POST /api/journeys/create   { title, description, ..., stops: [...] }
 *     -> { code, url }
 *   GET  /api/journeys/code/:code            -> stored journey JSON
 *   GET  /api/journeys/code/:code/geojson    -> synthesized route geojson
 *
 * Storage:
 *   JSON files at  Trip/shared-journeys/<CODE>.json
 *   (No DB — alphabet skips ambiguous chars; 7-char codes give ~78 billion combos.)
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SHARED_DIR = path.join(ROOT, "Trip", "shared-journeys");
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
const CODE_LENGTH = 7;
const MAX_TITLE_LEN = 120;
const MAX_DESCRIPTION_LEN = 400;
const MAX_HIGHLIGHTS = 8;
const MAX_STOPS = 32;

function ensureDir() {
  if (!fs.existsSync(SHARED_DIR)) {
    fs.mkdirSync(SHARED_DIR, { recursive: true });
  }
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

function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(payload));
}

function generateCode() {
  ensureDir();
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const bytes = crypto.randomBytes(CODE_LENGTH);
    let code = "";
    for (let i = 0; i < CODE_LENGTH; i += 1) {
      code += CODE_ALPHABET[bytes[i] % CODE_ALPHABET.length];
    }
    if (!fs.existsSync(path.join(SHARED_DIR, `${code}.json`))) {
      return code;
    }
  }
  throw new Error("Could not allocate a unique journey code, please retry.");
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function sanitizeString(value, maxLen) {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().slice(0, maxLen);
}

function sanitizeStop(stop, index) {
  if (!stop || typeof stop !== "object") {
    return null;
  }
  const lat = Number(stop.lat);
  const lng = Number(stop.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return null;
  }
  if (lat < -85 || lat > 85 || lng < -180 || lng > 180) {
    return null;
  }
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
  if (!title) {
    throw new Error("title is required");
  }
  const stopsRaw = Array.isArray(input?.stops) ? input.stops.slice(0, MAX_STOPS) : [];
  const stops = stopsRaw
    .map((stop, index) => sanitizeStop(stop, index))
    .filter(Boolean);
  if (stops.length < 2) {
    throw new Error("A journey needs at least 2 stops with coordinates");
  }
  if (stops.length) {
    stops[stops.length - 1].stopType = "end";
  }
  const highlights = Array.isArray(input?.highlights)
    ? input.highlights
        .slice(0, MAX_HIGHLIGHTS)
        .map((line) => sanitizeString(line, 200))
        .filter(Boolean)
    : [];
  const region = sanitizeString(input?.region, 120);
  const continent = sanitizeString(input?.continent, 40) || "europe";
  const description = sanitizeString(input?.description, MAX_DESCRIPTION_LEN);
  const emoji = sanitizeString(input?.emoji, 6) || "🧭";
  const days = clamp(Number(input?.days) || stops.length, 1, 90);
  const author = sanitizeString(input?.author, 60);
  return {
    schemaVersion: 1,
    title,
    description,
    region,
    continent,
    emoji,
    days,
    highlights,
    author,
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
    const h = Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
    total += 2 * R * Math.asin(Math.sqrt(h));
  }
  return Math.round(total);
}

function buildGeojson(journey) {
  const stops = journey.stops || [];
  if (stops.length < 2) {
    return { type: "FeatureCollection", features: [] };
  }
  // Each leg from stops[i-1] -> stops[i] is travelled in stops[i].mode. Group
  // consecutive same-mode legs into one LineString, sharing boundary stops so
  // adjacent segments meet exactly. Mode transitions break the segment AT the
  // shared stop (not after it) so each leg is attributed to its own mode.
  const segments = [];
  let i = 0;
  while (i < stops.length - 1) {
    const legMode = stops[i + 1].mode || "drive";
    const coords = [[stops[i].lng, stops[i].lat]];
    while (
      i < stops.length - 1 &&
      (stops[i + 1].mode || "drive") === legMode
    ) {
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

function readStored(code) {
  const file = path.join(SHARED_DIR, `${code}.json`);
  if (!fs.existsSync(file)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch (err) {
    console.warn(`[journey-codes] corrupt file ${file}: ${err?.message || err}`);
    return null;
  }
}

export function journeyCodesApiPlugin() {
  const handle = async (req, res) => {
    const url = new URL(req.url, "http://localhost");
    const { pathname } = url;

    if (pathname === "/api/journeys/create" && req.method === "POST") {
      try {
        const body = await readBody(req);
        const journey = sanitizeJourney(body);
        const code = generateCode();
        const record = {
          ...journey,
          code,
          createdAt: new Date().toISOString(),
          distanceKm: approximateDistanceKm(journey.stops),
        };
        ensureDir();
        fs.writeFileSync(
          path.join(SHARED_DIR, `${code}.json`),
          JSON.stringify(record, null, 2),
          "utf-8"
        );
        sendJson(res, 201, {
          code,
          url: `/?journey=${code}`,
          journey: record,
        });
      } catch (err) {
        sendJson(res, 400, { error: err.message || "Invalid journey" });
      }
      return;
    }

    const detailMatch = pathname.match(/^\/api\/journeys\/code\/([A-Z0-9]+)$/);
    if (detailMatch && req.method === "GET") {
      const code = detailMatch[1].toUpperCase();
      const record = readStored(code);
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
      const record = readStored(code);
      if (!record) {
        sendJson(res, 404, { error: "Journey not found" });
        return;
      }
      sendJson(res, 200, buildGeojson(record));
      return;
    }

    sendJson(res, 404, { error: "Not found" });
  };

  const attach = (server) => {
    server.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith("/api/journeys")) {
        next();
        return;
      }
      try {
        await handle(req, res);
      } catch (err) {
        console.error("[journey-codes-api]", err);
        sendJson(res, 500, { error: err.message || "Server error" });
      }
    });
  };

  return {
    name: "journey-codes-api",
    configureServer(server) {
      attach(server);
    },
    configurePreviewServer(server) {
      attach(server);
    },
  };
}
