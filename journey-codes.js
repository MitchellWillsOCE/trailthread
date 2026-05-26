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
