/**
 * National parks catalog — SQLite-backed API (see server/parks-api.js).
 */
import { createCatalogClient } from "./_catalog-client.js";

const client = createCatalogClient({
  basePath: "/api/parks",
  label: "parks catalog",
  resultTypeTag: "park",
  defaultSearchLimit: 10,
});

export const loadParksManifest = client.loadManifest;
export const loadParkRegion = client.loadRegion;
export const fetchParkFeatures = client.fetchFeatures;
export const fetchParkById = client.fetchById;
export const searchParks = client.search;
