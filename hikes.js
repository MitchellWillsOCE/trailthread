/**
 * Hiking trail catalog — SQLite-backed API (see server/hikes-api.js).
 * Data source: OpenStreetMap (route=hiking relations).
 */
import { createCatalogClient } from "./_catalog-client.js";

const client = createCatalogClient({
  basePath: "/api/hikes",
  label: "hike catalog",
  throwOnSearchFail: true,
});

export const loadHikesManifest = client.loadManifest;
export const loadHikeRegion = client.loadRegion;
export const fetchHikeFeatures = client.fetchFeatures;
export const fetchHikeById = client.fetchById;
export const searchHikes = client.search;
