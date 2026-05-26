/**
 * Resolves project-relative paths in a way that works in both `vite dev`
 * (cwd = project root) and Vercel serverless functions (where this file is
 * bundled at /var/task/api/_lib/paths.js and we walk two levels up).
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export const ROOT = path.resolve(__dirname, "..", "..");

export const PATHS = {
  citiesDb: path.join(ROOT, "Trip", "cities", "cities.db"),
  citiesManifest: path.join(ROOT, "Trip", "cities", "manifest.json"),
  citiesGeojson: path.join(ROOT, "Trip", "cities", "europe", "cities.geojson"),
  countryPopulations: path.join(ROOT, "Trip", "cities", "country-populations.json"),

  hikesDb: path.join(ROOT, "Trip", "hikes", "hikes.db"),
  hikesManifest: path.join(ROOT, "Trip", "hikes", "manifest.json"),

  parksDb: path.join(ROOT, "Trip", "parks", "parks.db"),
  parksManifest: path.join(ROOT, "Trip", "parks", "manifest.json"),

  poiDb: path.join(ROOT, "Trip", "poi", "poi.db"),
  poiManifest: path.join(ROOT, "Trip", "poi", "manifest.json"),

  sharedJourneys: path.join(ROOT, "Trip", "shared-journeys"),
  seasonHints: path.join(ROOT, "scripts", "data", "country-seasons.json"),
};
