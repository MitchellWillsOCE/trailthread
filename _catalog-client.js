/**
 * Shared catalog client factory.
 *
 * The cities / parks / hikes / POI modules all hit the same shape of REST API
 * (`/api/<kind>/manifest`, `/.../features`, `/.../detail/:id`, `/.../search?q=`).
 * This factory builds the primitives once; per-kind modules wrap or extend.
 *
 * Each instance has its own private detail cache.
 */
function buildBoundsParams(bounds, zoom, countryCc) {
  const params = new URLSearchParams({
    west: String(bounds.west),
    south: String(bounds.south),
    east: String(bounds.east),
    north: String(bounds.north),
    zoom: String(zoom),
  });
  if (countryCc) {
    params.set("country", countryCc);
  }
  return params;
}

export function createCatalogClient({
  basePath,
  label,
  resultTypeTag = null,
  throwOnSearchFail = false,
  defaultSearchLimit = 12,
}) {
  if (!basePath) {
    throw new Error("createCatalogClient: basePath is required");
  }
  if (!label) {
    throw new Error("createCatalogClient: label is required");
  }

  const detailCache = new Map();

  async function loadManifest() {
    const response = await fetch(`${basePath}/manifest`);
    if (!response.ok) {
      throw new Error(`Could not load ${label} manifest.`);
    }
    return response.json();
  }

  async function loadRegion(regionId = "europe") {
    const manifest = await loadManifest();
    const region = manifest.regions?.find((item) => item.id === regionId);
    if (!region) {
      throw new Error(`Unknown ${label} region: ${regionId}`);
    }
    return {
      id: region.id,
      label: region.label,
      count: region.count || 0,
      usesDatabase: manifest.storage === "sqlite",
    };
  }

  async function fetchFeatures(regionId, bounds, zoom, { countryCc = null } = {}) {
    const params = buildBoundsParams(bounds, zoom, countryCc);
    const response = await fetch(`${basePath}/${regionId}/features?${params}`);
    if (!response.ok) {
      throw new Error(`Could not load ${label} features for map bounds.`);
    }
    return response.json();
  }

  async function fetchById(id) {
    if (detailCache.has(id)) {
      return detailCache.get(id);
    }
    const response = await fetch(`${basePath}/detail/${encodeURIComponent(id)}`);
    if (!response.ok) {
      throw new Error(`Could not load ${label} detail.`);
    }
    const detail = await response.json();
    detailCache.set(id, detail);
    return detail;
  }

  async function search(query, { regionId = "europe", limit = defaultSearchLimit } = {}) {
    const q = String(query || "").trim();
    if (q.length < 2) {
      return [];
    }
    const params = new URLSearchParams({ q, region: regionId, limit: String(limit) });
    const response = await fetch(`${basePath}/search?${params}`);
    if (!response.ok) {
      if (throwOnSearchFail) {
        throw new Error(`${label} search failed.`);
      }
      return [];
    }
    const payload = await response.json();
    const results = payload.results || [];
    return resultTypeTag ? results.map((item) => ({ type: resultTypeTag, ...item })) : results;
  }

  return { loadManifest, loadRegion, fetchFeatures, fetchById, search, detailCache };
}
