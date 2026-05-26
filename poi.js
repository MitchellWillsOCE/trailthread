/**
 * Points of interest catalog — SQLite-backed API (see server/poi-api.js).
 */
import { createCatalogClient } from "./_catalog-client.js";

const client = createCatalogClient({
  basePath: "/api/poi",
  label: "POI catalog",
  resultTypeTag: "poi",
  defaultSearchLimit: 10,
});

export const loadPoisManifest = client.loadManifest;
export const loadPoiRegion = client.loadRegion;
export const fetchPoiFeatures = client.fetchFeatures;
export const fetchPoiById = client.fetchById;
export const searchPois = client.search;
