/**
 * Shared Vercel function config. Each per-prefix function file imports this
 * so they all bundle the same data dependencies. The `includeFiles` glob
 * lists every static catalog asset and bundled legacy shared-journey that
 * the handlers may read at runtime.
 */
export const config = {
  maxDuration: 15,
  includeFiles: [
    "Trip/cities/cities.db",
    "Trip/cities/manifest.json",
    "Trip/cities/country-populations.json",
    "Trip/cities/europe/cities.geojson",
    "Trip/cities/europe/details.json",
    "Trip/cities/oceania/cities.geojson",
    "Trip/cities/oceania/details.json",
    "Trip/hikes/hikes.db",
    "Trip/hikes/manifest.json",
    "Trip/hikes/europe/hikes-index.geojson",
    "Trip/hikes/oceania/hikes-index.geojson",
    "Trip/parks/parks.db",
    "Trip/parks/manifest.json",
    "Trip/poi/poi.db",
    "Trip/poi/manifest.json",
    "Trip/shared-journeys/*.json",
    "scripts/data/country-seasons.json",
  ],
};
