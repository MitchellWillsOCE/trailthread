/**
 * Country dossier API client.
 *
 * `fetchCountryDossier(cc)` returns the joined catalog summary for a country.
 */
const cache = new Map();

export async function fetchCountryDossier(cc) {
  const code = String(cc || "").trim().toLowerCase();
  if (!/^[a-z]{2}$/.test(code)) {
    throw new Error("Invalid country code");
  }
  if (cache.has(code)) {
    return cache.get(code);
  }
  const response = await fetch(`/api/country/${code}`);
  if (!response.ok) {
    throw new Error(`Country dossier failed (${response.status})`);
  }
  const data = await response.json();
  cache.set(code, data);
  return data;
}

export function invalidateCountryDossier(cc) {
  if (cc) {
    cache.delete(String(cc).toLowerCase());
  } else {
    cache.clear();
  }
}
