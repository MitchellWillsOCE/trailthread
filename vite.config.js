import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import { citiesApiPlugin } from "./server/cities-api.js";
import { hikesApiPlugin } from "./server/hikes-api.js";
import { parksApiPlugin } from "./server/parks-api.js";
import { poiApiPlugin } from "./server/poi-api.js";
import { countryDossierApiPlugin } from "./server/country-dossier-api.js";
import { journeyCodesApiPlugin } from "./server/journey-codes-api.js";

/**
 * Copy a handful of repo-rooted static assets into `dist/` at build time. The
 * client code fetches these directly (without going through the API), so they
 * must be served as static files in production. SQLite catalogs and the
 * shared-journeys JSON are intentionally NOT copied — those are server-only
 * and ship with the Vercel function bundle via `includeFiles` instead.
 */
function copyStaticAssetsPlugin() {
  const STATIC_FILES = [
    "favicon.svg",
    "service-worker.js",
    "Trip/journeys.json",
    "Trip/place-details.json",
    "Trip/ferry-routes.json",
    "Trip/transit-routes.json",
    "Trip/geo/europe-countries.geojson",
    "scripts/data/country-seasons.json",
  ];
  return {
    name: "copy-static-assets",
    apply: "build",
    closeBundle() {
      const outDir = path.resolve("dist");
      for (const rel of STATIC_FILES) {
        const src = path.resolve(rel);
        const dest = path.join(outDir, rel);
        if (!fs.existsSync(src)) {
          this.warn(`[copy-static-assets] missing source: ${rel}`);
          continue;
        }
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.copyFileSync(src, dest);
      }
    },
  };
}

export default defineConfig({
  plugins: [
    citiesApiPlugin(),
    hikesApiPlugin(),
    parksApiPlugin(),
    poiApiPlugin(),
    countryDossierApiPlugin(),
    journeyCodesApiPlugin(),
    copyStaticAssetsPlugin(),
  ],
});
