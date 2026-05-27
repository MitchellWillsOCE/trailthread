import fs from "node:fs";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import { citiesApiPlugin } from "./server/cities-api.js";
import { hikesApiPlugin } from "./server/hikes-api.js";
import { parksApiPlugin } from "./server/parks-api.js";
import { poiApiPlugin } from "./server/poi-api.js";
import { countryDossierApiPlugin } from "./server/country-dossier-api.js";
import { journeyCodesApiPlugin } from "./server/journey-codes-api.js";

/**
 * Copy repo-rooted static assets into `dist/` at build time. The client code
 * fetches these directly (without going through the API), so they must be
 * served as static files in production. SQLite catalogs and the
 * shared-journeys JSON are intentionally NOT copied — those are server-only
 * and ship with the Vercel function bundle via `includeFiles` instead.
 *
 * Two passes:
 *  1. Explicit list of single files at known paths.
 *  2. Recursive walk of `Trip/` to pick up every journey folder's
 *     `*.geojson` and `*.md` (route + itinerary) plus the root-level
 *     manifest/lookup JSON files, while skipping the server-only
 *     subdirectories (`cities/`, `hikes/`, `parks/`, `poi/`,
 *     `shared-journeys/`).
 */
function copyStaticAssetsPlugin() {
  const STATIC_FILES = [
    "favicon.svg",
    "service-worker.js",
    "scripts/data/country-seasons.json",
  ];

  // Subdirectories inside Trip/ that are server-only and must NOT be copied
  // to the public static bundle.
  const TRIP_SERVER_ONLY_DIRS = new Set([
    "cities",
    "hikes",
    "parks",
    "poi",
    "shared-journeys",
  ]);

  // File extensions inside Trip/ that the client fetches directly.
  const TRIP_CLIENT_EXTENSIONS = new Set([".geojson", ".md", ".json"]);

  function copyFile(src, dest) {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
  }

  function walkTripDir(rootRel, outDir, logger) {
    const rootAbs = path.resolve(rootRel);
    if (!fs.existsSync(rootAbs)) {
      logger.warn(`[copy-static-assets] missing source dir: ${rootRel}`);
      return 0;
    }
    let copied = 0;
    const stack = [rootAbs];
    while (stack.length) {
      const dir = stack.pop();
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const abs = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          // At the top level of Trip/, skip server-only subfolders entirely.
          if (
            dir === rootAbs &&
            TRIP_SERVER_ONLY_DIRS.has(entry.name)
          ) {
            continue;
          }
          stack.push(abs);
          continue;
        }
        const ext = path.extname(entry.name).toLowerCase();
        if (!TRIP_CLIENT_EXTENSIONS.has(ext)) {
          continue;
        }
        const rel = path.relative(path.resolve("."), abs);
        const dest = path.join(outDir, rel);
        copyFile(abs, dest);
        copied += 1;
      }
    }
    return copied;
  }

  return {
    name: "copy-static-assets",
    apply: "build",
    closeBundle() {
      const outDir = path.resolve("dist");

      for (const rel of STATIC_FILES) {
        const src = path.resolve(rel);
        if (!fs.existsSync(src)) {
          this.warn(`[copy-static-assets] missing source: ${rel}`);
          continue;
        }
        copyFile(src, path.join(outDir, rel));
      }

      const tripCount = walkTripDir("Trip", outDir, this);
      // eslint-disable-next-line no-console
      console.log(`[copy-static-assets] copied ${tripCount} Trip/ asset(s)`);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  Object.assign(process.env, env);

  return {
    plugins: [
      citiesApiPlugin(),
      hikesApiPlugin(),
      parksApiPlugin(),
      poiApiPlugin(),
      countryDossierApiPlugin(),
      journeyCodesApiPlugin(),
      copyStaticAssetsPlugin(),
    ],
  };
});
