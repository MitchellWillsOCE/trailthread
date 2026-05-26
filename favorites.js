/**
 * Local favorites (hearted places) — persisted in localStorage.
 *
 * Each entry: { id, kind, name, country, lat, lng, photo, tagline, addedAt }
 *
 * Use:
 *   getFavorites()                  -> array of favs (most-recent first)
 *   isFavorite(kind, id)            -> bool
 *   toggleFavorite(entry)           -> bool (new state)
 *   removeFavorite(kind, id)        -> bool removed
 *   subscribeFavorites(handler)     -> unsubscribe fn
 */
const STORAGE_KEY = "trailthread/favorites";
const MAX_FAVORITES = 80;
const listeners = new Set();
let cache = null;

function readRaw() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeRaw(value) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch (err) {
    console.warn("[favorites] could not persist", err);
  }
}

function ensureCache() {
  if (!cache) {
    cache = readRaw();
  }
  return cache;
}

function notify() {
  listeners.forEach((fn) => {
    try {
      fn(getFavorites());
    } catch (err) {
      console.warn("[favorites] listener failed", err);
    }
  });
}

function favKey(kind, id) {
  return `${kind || "stop"}::${id || ""}`;
}

export function getFavorites() {
  return ensureCache().slice();
}

export function isFavorite(kind, id) {
  if (!id) return false;
  return ensureCache().some((entry) => favKey(entry.kind, entry.id) === favKey(kind, id));
}

export function removeFavorite(kind, id) {
  const list = ensureCache();
  const key = favKey(kind, id);
  const idx = list.findIndex((entry) => favKey(entry.kind, entry.id) === key);
  if (idx === -1) return false;
  list.splice(idx, 1);
  cache = list.slice();
  writeRaw(cache);
  notify();
  return true;
}

export function addFavorite(entry) {
  if (!entry || !entry.id || !entry.kind) {
    return false;
  }
  if (!Number.isFinite(entry.lat) || !Number.isFinite(entry.lng)) {
    return false;
  }
  const list = ensureCache().filter(
    (existing) => favKey(existing.kind, existing.id) !== favKey(entry.kind, entry.id)
  );
  list.unshift({
    id: entry.id,
    kind: entry.kind,
    name: entry.name || "Saved place",
    country: entry.country || "",
    lat: entry.lat,
    lng: entry.lng,
    photo: entry.photo || "",
    tagline: entry.tagline || "",
    addedAt: Date.now(),
  });
  cache = list.slice(0, MAX_FAVORITES);
  writeRaw(cache);
  notify();
  return true;
}

export function toggleFavorite(entry) {
  if (isFavorite(entry?.kind, entry?.id)) {
    removeFavorite(entry.kind, entry.id);
    return false;
  }
  return addFavorite(entry) && true;
}

export function subscribeFavorites(handler) {
  if (typeof handler !== "function") {
    return () => {};
  }
  listeners.add(handler);
  return () => listeners.delete(handler);
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) {
      cache = null;
      notify();
    }
  });
}
