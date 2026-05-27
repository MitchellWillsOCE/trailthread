/**
 * Shared journey codes — client API.
 *
 * createSharedJourney(journey) -> { code, url, journey }
 * fetchSharedJourney(code)     -> stored journey record
 * fetchSharedJourneyGeojson(code) -> synthesized FeatureCollection
 */
const BASE = "/api/journeys";
const detailCache = new Map();
const geojsonCache = new Map();

export async function createSharedJourney(payload) {
  const response = await fetch(`${BASE}/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `Could not create journey (${response.status})`);
  }
  const data = await response.json();
  detailCache.set(data.code, data.journey);
  return data;
}

function normaliseCode(code) {
  return String(code || "").trim().toUpperCase();
}

export async function fetchSharedJourney(code) {
  const c = normaliseCode(code);
  if (!c) {
    throw new Error("Code is required");
  }
  if (detailCache.has(c)) {
    return detailCache.get(c);
  }
  const response = await fetch(`${BASE}/code/${encodeURIComponent(c)}`);
  if (!response.ok) {
    throw new Error("Journey not found");
  }
  const detail = await response.json();
  detailCache.set(c, detail);
  return detail;
}

export async function fetchSharedJourneyGeojson(code) {
  const c = normaliseCode(code);
  if (geojsonCache.has(c)) {
    return geojsonCache.get(c);
  }
  const response = await fetch(`${BASE}/code/${encodeURIComponent(c)}/geojson`);
  if (!response.ok) {
    throw new Error("Could not load journey route");
  }
  const geo = await response.json();
  geojsonCache.set(c, geo);
  return geo;
}

export function isJourneyCode(value) {
  return /^[A-Z2-9]{4,12}$/i.test(String(value || "").trim());
}

/* ---------------------------------------------------------------------------
 * Self-contained share links
 *
 * The short server-minted code (e.g. /?journey=ABC1234) requires the API to
 * be reachable AND to find the record in storage on whichever device opens
 * it. In production that depends on the Upstash KV / Redis integration
 * being configured; without it, journeys minted on one client cannot be
 * loaded from another (the function disk is ephemeral on Vercel).
 *
 * To make share links work cross-client without server-side state, we also
 * encode the journey payload directly into the URL via a `?j=` query param
 * (base64url JSON). Anyone who opens the link gets the journey loaded
 * client-side from the URL itself, even when the API is not reachable.
 * ------------------------------------------------------------------------- */

function toBase64Url(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 1) {
    bin += String.fromCharCode(bytes[i]);
  }
  return btoa(bin)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function fromBase64Url(token) {
  const padded = token.replace(/-/g, "+").replace(/_/g, "/");
  const padLen = (4 - (padded.length % 4)) % 4;
  const bin = atob(padded + "=".repeat(padLen));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    bytes[i] = bin.charCodeAt(i);
  }
  return new TextDecoder().decode(bytes);
}

function trimToNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Compact a journey object into the smallest reasonable JSON shape for URL. */
function encodeJourneyPayload(journey) {
  const stops = (Array.isArray(journey?.stops) ? journey.stops : [])
    .map((stop) => {
      const lat = trimToNumber(stop?.lat);
      const lng = trimToNumber(stop?.lng);
      if (lat == null || lng == null) return null;
      const compact = {
        n: String(stop.name || "").slice(0, 120),
        lat: Number(lat.toFixed(5)),
        lng: Number(lng.toFixed(5)),
      };
      if (stop.country) compact.c = String(stop.country).slice(0, 80);
      if (stop.kind && stop.kind !== "stop") compact.k = String(stop.kind).slice(0, 16);
      if (stop.mode && stop.mode !== "drive") compact.m = String(stop.mode).slice(0, 12);
      if (stop.stopType) compact.p = String(stop.stopType).slice(0, 12);
      if (stop.day) compact.d = String(stop.day).slice(0, 12);
      if (stop.tagline) compact.g = String(stop.tagline).slice(0, 160);
      if (stop.id) compact.i = String(stop.id).slice(0, 80);
      return compact;
    })
    .filter(Boolean);

  const payload = {
    v: 1,
    t: String(journey?.title || "Shared journey").slice(0, 120),
    s: stops,
  };
  if (journey?.description) payload.dd = String(journey.description).slice(0, 400);
  if (journey?.region) payload.r = String(journey.region).slice(0, 120);
  if (journey?.continent) payload.c = String(journey.continent).slice(0, 40);
  if (journey?.emoji) payload.e = String(journey.emoji).slice(0, 6);
  if (journey?.author) payload.a = String(journey.author).slice(0, 60);
  if (journey?.days) payload.n = Number(journey.days) || stops.length;
  if (Array.isArray(journey?.highlights) && journey.highlights.length) {
    payload.h = journey.highlights
      .slice(0, 8)
      .map((line) => String(line).slice(0, 200))
      .filter(Boolean);
  }
  return payload;
}

export function encodeJourneyToToken(journey) {
  const payload = encodeJourneyPayload(journey);
  const json = JSON.stringify(payload);
  return toBase64Url(json);
}

export function decodeJourneyToken(token) {
  if (!token) return null;
  try {
    const json = fromBase64Url(String(token));
    const data = JSON.parse(json);
    if (!data || typeof data !== "object") return null;
    const stops = (Array.isArray(data.s) ? data.s : [])
      .map((stop, idx) => {
        const lat = trimToNumber(stop?.lat);
        const lng = trimToNumber(stop?.lng);
        if (lat == null || lng == null) return null;
        return {
          id: stop.i ? String(stop.i) : `stop-${idx + 1}`,
          name: stop.n ? String(stop.n) : `Stop ${idx + 1}`,
          country: stop.c ? String(stop.c) : "",
          kind: stop.k ? String(stop.k) : "stop",
          mode: stop.m ? String(stop.m) : "drive",
          stopType: stop.p
            ? String(stop.p)
            : idx === 0
              ? "start"
              : "city",
          day: stop.d ? String(stop.d) : "",
          tagline: stop.g ? String(stop.g) : "",
          lat,
          lng,
        };
      })
      .filter(Boolean);
    if (stops.length < 2) return null;
    if (stops[stops.length - 1]) {
      stops[stops.length - 1].stopType = "end";
    }
    return {
      schemaVersion: 1,
      title: data.t ? String(data.t) : "Shared journey",
      description: data.dd ? String(data.dd) : "",
      region: data.r ? String(data.r) : "",
      continent: data.c ? String(data.c) : "europe",
      emoji: data.e ? String(data.e) : "🧭",
      days: Number(data.n) || stops.length,
      highlights: Array.isArray(data.h) ? data.h.map(String).filter(Boolean) : [],
      author: data.a ? String(data.a) : "",
      stops,
    };
  } catch (err) {
    console.warn("[journey decode]", err);
    return null;
  }
}

/** Synthesize the same FeatureCollection shape the server produces. */
export function buildJourneyGeojson(journey) {
  const stops = Array.isArray(journey?.stops) ? journey.stops : [];
  if (stops.length < 2) return { type: "FeatureCollection", features: [] };
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
      properties: {
        name: `${journey.title || "Journey"} — ${legMode}`,
        mode: legMode,
      },
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

export function approximateJourneyDistanceKm(stops) {
  if (!Array.isArray(stops) || stops.length < 2) return 0;
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
