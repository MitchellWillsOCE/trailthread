/* Trailthread service worker.
 *
 *  - precaches the app shell so the site opens offline
 *  - stale-while-revalidate for catalog GET API requests + manifests
 *  - cache-first with size cap for remote photo CDNs (Wikimedia / Wikipedia)
 *  - network-only for journey-code mutations
 */
// Bump the version whenever shipping a fix that changes app shell or JS
// behaviour so old SW caches (which serve stale assets via
// stale-while-revalidate) are dropped on next visit. The build pipeline
// hashes asset paths but the previous SW could still hand back old HTML.
const SW_VERSION = "tt-v10-typical-journeys";
const SHELL_CACHE = `${SW_VERSION}-shell`;
const RUNTIME_CACHE = `${SW_VERSION}-runtime`;
const PHOTOS_CACHE = `${SW_VERSION}-photos`;

// Note: built CSS/JS/webmanifest live at hashed paths under /assets/ in
// production; relying on runtime caching for those rather than enumerating
// here. The listed paths are stable (HTML entry + repo-rooted JSON catalogs).
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/favicon.svg",
  "/Trip/journeys.json",
  "/Trip/place-details.json",
  "/scripts/data/country-seasons.json"
];

const PHOTO_HOST_PATTERN = /(commons\.wikimedia\.org|upload\.wikimedia\.org|wikipedia\.org)/;
const PHOTO_CACHE_LIMIT = 240;

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      await Promise.all(
        SHELL_ASSETS.map((url) =>
          cache.add(url).catch((err) => console.warn("[sw] shell skip", url, err?.message))
        )
      );
      self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => !key.startsWith(SW_VERSION))
          .map((key) => caches.delete(key))
      );
      await self.clients.claim();
    })()
  );
});

async function trimCache(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length <= maxEntries) {
    return;
  }
  const toDelete = keys.length - maxEntries;
  for (let i = 0; i < toDelete; i += 1) {
    await cache.delete(keys[i]);
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok && response.status === 200) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);
  return cached || network;
}

async function cacheFirstPhoto(request) {
  const cache = await caches.open(PHOTOS_CACHE);
  const cached = await cache.match(request);
  if (cached) {
    return cached;
  }
  try {
    // Preserve the original request mode (typically `no-cors` for <img> tags).
    // Wikimedia's Special:FilePath URLs 302-redirect without CORS headers, so
    // forcing `mode: "cors"` would fail the redirect. Opaque responses still
    // render fine in <img> and can be cached for offline use.
    const response = await fetch(request);
    if (response && (response.ok || response.type === "opaque")) {
      cache
        .put(request, response.clone())
        .then(() => trimCache(PHOTOS_CACHE, PHOTO_CACHE_LIMIT))
        .catch(() => {});
    }
    return response;
  } catch (err) {
    return cached || Response.error();
  }
}

async function networkFirstShell(request) {
  try {
    const response = await fetch(request);
    if (response.ok && new URL(request.url).origin === self.location.origin) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cache = await caches.open(SHELL_CACHE);
    const cached = await cache.match(request, { ignoreSearch: true });
    return cached || cache.match("/index.html");
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (request.mode === "navigate") {
    event.respondWith(networkFirstShell(request));
    return;
  }

  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (url.origin === self.location.origin && (url.pathname.startsWith("/Trip/") || url.pathname.startsWith("/scripts/data/"))) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (PHOTO_HOST_PATTERN.test(url.host)) {
    event.respondWith(cacheFirstPhoto(request));
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(request));
  }
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") {
    self.skipWaiting();
  }
});
