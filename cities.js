/**
 * City catalog — SQLite-backed API (see server/cities-api.js).
 *
 * Wraps the shared catalog client and adds city-specific endpoints
 * (countries list, population stats, name lookup) plus a synthetic
 * detail fallback used when the API is unavailable.
 */
import { createCatalogClient } from "./_catalog-client.js";

const API_BASE = "/api/cities";

const client = createCatalogClient({
  basePath: API_BASE,
  label: "city catalog",
  resultTypeTag: "city",
  throwOnSearchFail: true,
});

const { detailCache, loadManifest, loadRegion, fetchFeatures, search } = client;

export const loadCitiesManifest = loadManifest;
export const loadCityRegion = loadRegion;
export const fetchCityFeatures = fetchFeatures;
export const searchCities = search;

export async function fetchCountries(regionId = "europe") {
  const response = await fetch(`${API_BASE}/${regionId}/countries`);
  if (!response.ok) {
    throw new Error("Could not load countries list.");
  }
  const payload = await response.json();
  return payload.countries || [];
}

/** National population + largest catalog city per country (for marker weighting). */
export async function fetchCountryPopStats(regionId = "europe") {
  const response = await fetch(`${API_BASE}/${regionId}/pop-stats`);
  if (!response.ok) {
    throw new Error("Could not load country population stats.");
  }
  return response.json();
}

export async function fetchCityById(cityId, fallbackProps = {}) {
  if (detailCache.has(cityId)) {
    return detailCache.get(cityId);
  }
  const response = await fetch(`${API_BASE}/detail/${encodeURIComponent(cityId)}`);
  if (response.ok) {
    const detail = await response.json();
    detailCache.set(cityId, detail);
    return detail;
  }
  return getCityDetail(null, cityId, fallbackProps);
}

export function searchCountries(query, countries, { limit = 4 } = {}) {
  const q = String(query || "").trim().toLowerCase();
  if (q.length < 2 || !countries?.length) {
    return [];
  }
  return countries
    .filter((item) => {
      const name = item.country?.toLowerCase() || "";
      const cc = item.cc?.toLowerCase() || "";
      return name.includes(q) || cc === q || name.startsWith(q);
    })
    .sort((a, b) => {
      const nameA = a.country?.toLowerCase() || "";
      const nameB = b.country?.toLowerCase() || "";
      const exactA = nameA === q || a.cc?.toLowerCase() === q;
      const exactB = nameB === q || b.cc?.toLowerCase() === q;
      if (exactA !== exactB) {
        return exactA ? -1 : 1;
      }
      if (nameA.startsWith(q) !== nameB.startsWith(q)) {
        return nameA.startsWith(q) ? -1 : 1;
      }
      return (b.cityCount || 0) - (a.cityCount || 0);
    })
    .slice(0, limit)
    .map((item) => ({
      type: "country",
      id: `country-${item.cc}`,
      name: item.country,
      country: item.country,
      cc: item.cc,
      cityCount: item.cityCount,
      bounds: item.bounds,
    }));
}

export async function searchPlaces(
  query,
  { regionId = "europe", countries = [], cityLimit = 10, countryLimit = 4 } = {}
) {
  const q = String(query || "").trim();
  if (q.length < 2) {
    return [];
  }
  const countryHits = searchCountries(q, countries, { limit: countryLimit });
  const cityHits = await searchCities(q, { regionId, limit: cityLimit });
  return [...countryHits, ...cityHits];
}

export async function lookupCityByName(name, country = "") {
  const key = `${name}|${country}`.toLowerCase();
  if (detailCache.has(key)) {
    return detailCache.get(key);
  }
  const params = new URLSearchParams({ name });
  if (country) {
    params.set("country", country);
  }
  const response = await fetch(`${API_BASE}/lookup?${params}`);
  if (!response.ok) {
    return null;
  }
  const detail = await response.json();
  detailCache.set(key, detail);
  detailCache.set(detail.id, detail);
  return detail;
}

/**
 * Synthetic fallback detail when the API is unavailable. The first arg is
 * accepted for back-compat (older callers passed a catalog object); ignored.
 */
export function getCityDetail(_catalog, cityId, props = {}) {
  const cached = detailCache.get(cityId);
  if (cached) {
    return cached;
  }
  const name = props.name || "City";
  const country = props.country || "";
  return {
    id: cityId,
    name,
    country,
    cc: props.cc || "",
    general: `${name} is a destination in ${country || "Europe"}.`,
    activities: ["Old town walk", "Local café stop", "Viewpoint visit"],
    tips: [],
    tagline: props.tagline || `Discover ${name}`,
    photos: [],
  };
}
