/**
 * Vercel serverless catch-all that dispatches every `/api/*` request to the
 * matching shared handler in `api/_lib/handlers/`. The same handlers are
 * mounted as Vite middleware in `server/*-api.js` for local dev — one source
 * of truth for both environments.
 *
 * `includeFiles` ships the SQLite catalogs, GeoJSON fallbacks, manifests, and
 * legacy shared-journey JSON files into the function bundle so they're
 * readable at runtime via the paths in `api/_lib/paths.js`.
 */
import { handleCities } from "./_lib/handlers/cities.js";
import { handleHikes } from "./_lib/handlers/hikes.js";
import { handleParks } from "./_lib/handlers/parks.js";
import { handlePoi } from "./_lib/handlers/poi.js";
import { handleCountry } from "./_lib/handlers/country.js";
import { handleJourneys } from "./_lib/handlers/journeys.js";
import { sendJson } from "./_lib/sql-shared.js";

export const config = {
  runtime: "nodejs20.x",
  maxDuration: 15,
  includeFiles: [
    "Trip/cities/cities.db",
    "Trip/cities/manifest.json",
    "Trip/cities/country-populations.json",
    "Trip/cities/europe/cities.geojson",
    "Trip/cities/europe/details.json",
    "Trip/hikes/hikes.db",
    "Trip/hikes/manifest.json",
    "Trip/hikes/europe/hikes-index.geojson",
    "Trip/parks/parks.db",
    "Trip/parks/manifest.json",
    "Trip/poi/poi.db",
    "Trip/poi/manifest.json",
    "Trip/shared-journeys/**",
    "scripts/data/country-seasons.json",
  ],
};

export default async function handler(req, res) {
  try {
    const url = new URL(req.url, "http://localhost");
    const { pathname } = url;

    if (pathname.startsWith("/api/cities")) return handleCities(req, res, url);
    if (pathname.startsWith("/api/hikes")) return handleHikes(req, res, url);
    if (pathname.startsWith("/api/parks")) return handleParks(req, res, url);
    if (pathname.startsWith("/api/poi")) return handlePoi(req, res, url);
    if (pathname.startsWith("/api/country/")) return handleCountry(req, res, url);
    if (pathname.startsWith("/api/journeys")) return handleJourneys(req, res, url);

    sendJson(res, 404, { error: "Not found" });
  } catch (err) {
    console.error("[api]", err);
    if (!res.headersSent) {
      sendJson(res, 500, { error: err?.message || "Internal error" });
    }
  }
}
