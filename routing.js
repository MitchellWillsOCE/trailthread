/**
 * Snap route geometry to OSM networks via the public OSRM API.
 * drive -> driving profile; hike -> foot; train/ferry use baked OSM catalogs;
 * fly -> great-circle arcs.
 */

const OSRM_BASE = "https://router.project-osrm.org/route/v1";
const routeCache = new Map();

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function toDeg(rad) {
  return (rad * 180) / Math.PI;
}

/** Direct origin-to-destination path for flights (great-circle arc). */
export function flightLineCoordinates(coords, steps = 32) {
  if (!coords?.length) {
    return coords;
  }
  if (coords.length === 1) {
    return coords;
  }

  const [lng1, lat1] = coords[0];
  const [lng2, lat2] = coords[coords.length - 1];

  const lat1r = toRad(lat1);
  const lat2r = toRad(lat2);
  const lng1r = toRad(lng1);
  const lng2r = toRad(lng2);
  const d =
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin((lat2r - lat1r) / 2) ** 2 +
          Math.cos(lat1r) * Math.cos(lat2r) * Math.sin((lng2r - lng1r) / 2) ** 2
      )
    );

  if (d < 1e-9) {
    return [[lng1, lat1], [lng2, lat2]];
  }

  const result = [];
  for (let i = 0; i <= steps; i += 1) {
    const f = i / steps;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(lat1r) * Math.cos(lng1r) + B * Math.cos(lat2r) * Math.cos(lng2r);
    const y = A * Math.cos(lat1r) * Math.sin(lng1r) + B * Math.cos(lat2r) * Math.sin(lng2r);
    const z = A * Math.sin(lat1r) + B * Math.sin(lat2r);
    result.push([toDeg(Math.atan2(y, x)), toDeg(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
  }
  return result;
}

let ferryRoutesCatalogPromise = null;

/** Load baked OSM ferry geometries (see scripts/build-ferry-routes.py). */
export async function loadFerryRoutesCatalog() {
  if (!ferryRoutesCatalogPromise) {
    ferryRoutesCatalogPromise = fetch("./Trip/ferry-routes.json")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`ferry-routes.json (${response.status})`);
        }
        return response.json();
      })
      .catch((error) => {
        ferryRoutesCatalogPromise = null;
        throw error;
      });
  }
  return ferryRoutesCatalogPromise;
}

export function ferryRouteFromCatalog(catalog, ferryRouteId) {
  const route = catalog?.routes?.[ferryRouteId];
  if (!route?.coordinates?.length || route.coordinates.length < 2) {
    return null;
  }
  return route;
}

let transitRoutesCatalogPromise = null;

/** Load baked OSM rail geometries (see scripts/build-transit-routes.py). */
export async function loadTransitRoutesCatalog() {
  if (!transitRoutesCatalogPromise) {
    transitRoutesCatalogPromise = fetch("./Trip/transit-routes.json")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`transit-routes.json (${response.status})`);
        }
        return response.json();
      })
      .catch((error) => {
        transitRoutesCatalogPromise = null;
        throw error;
      });
  }
  return transitRoutesCatalogPromise;
}

export function transitRouteFromCatalog(catalog, transitRouteId) {
  const route = catalog?.routes?.[transitRouteId];
  if (!route?.coordinates?.length || route.coordinates.length < 2) {
    return null;
  }
  return route;
}

/** Apply mode-specific geometry before the map draws a line (fly only; ferries resolved at load). */
export function normalizeLineFeature(feature) {
  if (feature?.geometry?.type !== "LineString") {
    return feature;
  }

  const mode = feature.properties?.mode || "drive";
  if (mode !== "fly") {
    return feature;
  }

  const coords = feature.geometry.coordinates;
  const shaped = flightLineCoordinates(coords);
  if (shaped === coords) {
    return feature;
  }

  return {
    ...feature,
    geometry: {
      type: "LineString",
      coordinates: shaped
    }
  };
}

function coordKey(coords, mode) {
  const sample = coords
    .filter((_, i) => i === 0 || i === coords.length - 1 || i % Math.max(1, Math.floor(coords.length / 4)) === 0)
    .map(([lng, lat]) => `${lng.toFixed(4)},${lat.toFixed(4)}`)
    .join("|");
  return `${mode}:${sample}:${coords.length}`;
}

function haversineKm(a, b) {
  const toRad = (d) => (d * Math.PI) / 180;
  const [lng1, lat1] = a;
  const [lng2, lat2] = b;
  const R = 6371;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

export function lineLengthKm(coords) {
  let total = 0;
  for (let i = 1; i < coords.length; i += 1) {
    total += haversineKm(coords[i - 1], coords[i]);
  }
  return total;
}

async function fetchOsrmRoute(coords, profile) {
  if (coords.length < 2) {
    return coords;
  }

  const limited = coords.length > 90 ? downsampleCoords(coords, 90) : coords;
  const path = limited.map(([lng, lat]) => `${lng},${lat}`).join(";");
  const url = `${OSRM_BASE}/${profile}/${path}?overview=full&geometries=geojson&steps=false`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`OSRM ${response.status}`);
  }

  const data = await response.json();
  if (data.code !== "Ok" || !data.routes?.[0]?.geometry?.coordinates) {
    throw new Error(data.message || "No route geometry");
  }

  return data.routes[0].geometry.coordinates;
}

function downsampleCoords(coords, maxPoints) {
  if (coords.length <= maxPoints) {
    return coords;
  }
  const result = [coords[0]];
  const step = (coords.length - 1) / (maxPoints - 1);
  for (let i = 1; i < maxPoints - 1; i += 1) {
    result.push(coords[Math.round(i * step)]);
  }
  result.push(coords[coords.length - 1]);
  return result;
}

/** Split a polyline where consecutive points jump farther than maxGapKm (bad OSM joins). */
export function splitCoordsAtJumps(coords, maxGapKm = 2.5) {
  if (!coords?.length) {
    return [];
  }
  if (coords.length < 2) {
    return [coords];
  }

  const chains = [[coords[0]]];
  for (let i = 1; i < coords.length; i += 1) {
    const prev = coords[i - 1];
    const cur = coords[i];
    if (haversineKm(prev, cur) > maxGapKm) {
      if (chains[chains.length - 1].length >= 2) {
        chains.push([cur]);
      } else {
        chains[chains.length - 1].push(cur);
      }
    } else {
      chains[chains.length - 1].push(cur);
    }
  }

  return chains.filter((chain) => chain.length >= 2);
}

/**
 * Refine catalog trail geometry: drop jump chords, snap each contiguous chain to OSM foot paths.
 * Returns a GeoJSON LineString or MultiLineString.
 */
export async function refineHikeTrailGeometry(coords, { maxGapKm = 2.5 } = {}) {
  if (!coords?.length || coords.length < 2) {
    return null;
  }

  let widestGapKm = 0;
  for (let i = 1; i < coords.length; i += 1) {
    widestGapKm = Math.max(widestGapKm, haversineKm(coords[i - 1], coords[i]));
  }
  // Sparse catalog sketches (3–5 widely spaced waypoints) must not be split and
  // OSRM-snapped independently — that draws disconnected road fragments and
  // leaves start/finish markers off the visible path. Dense OSM traces should
  // also stay as-is so foot routing does not pull them onto nearby roads.
  if (coords.length >= 20 || widestGapKm > maxGapKm) {
    return { type: "LineString", coordinates: coords };
  }

  const chains = splitCoordsAtJumps(coords, maxGapKm);
  if (!chains.length) {
    return { type: "LineString", coordinates: coords };
  }

  const refined = [];
  for (const chain of chains) {
    const sample = chain.length > 24 ? downsampleCoords(chain, 24) : chain;
    try {
      const snapped = await snapLineCoordinates(sample, "hike");
      if (snapped?.length >= 2) {
        refined.push(snapped);
      }
    } catch {
      refined.push(chain);
    }
  }

  if (!refined.length) {
    return { type: "LineString", coordinates: coords };
  }
  if (refined.length === 1) {
    return { type: "LineString", coordinates: refined[0] };
  }
  return { type: "MultiLineString", coordinates: refined };
}

export async function snapLineCoordinates(coords, mode, options = {}) {
  if (!coords?.length || coords.length < 2) {
    return coords;
  }

  if (mode === "ferry") {
    return coords;
  }

  if (mode === "train" && options.osmTransit) {
    return coords;
  }

  if (mode === "fly") {
    return flightLineCoordinates(coords);
  }

  if (mode === "hike" && options.catalogTrail) {
    try {
      const refined = await refineHikeTrailGeometry(coords);
      if (refined?.type === "LineString" && refined.coordinates?.length >= 2) {
        return refined.coordinates;
      }
      if (refined?.type === "MultiLineString" && refined.coordinates?.length) {
        return refined.coordinates.flat();
      }
    } catch {
      /* keep catalog geometry */
    }
    return coords;
  }

  const profile = mode === "hike" ? "foot" : "driving";
  const key = coordKey(coords, profile);

  if (routeCache.has(key)) {
    return routeCache.get(key);
  }

  try {
    const snapped = await fetchOsrmRoute(coords, profile);
    routeCache.set(key, snapped);
    return snapped;
  } catch {
    return coords;
  }
}

export async function enrichLineFeature(feature) {
  if (feature?.geometry?.type !== "LineString") {
    return feature;
  }

  const mode = feature.properties?.mode || "drive";
  const coords = feature.geometry.coordinates;
  const catalogTrail = Boolean(feature.properties?.catalogTrail || feature.properties?.hikeId);
  const osmTransit = Boolean(feature.properties?.osmTransit || feature.properties?.transitRouteId);
  const snapped = await snapLineCoordinates(coords, mode, { catalogTrail, osmTransit });
  const distanceKm = lineLengthKm(snapped);

  let routeSource = "OpenStreetMap via OSRM";
  if (mode === "ferry") {
    routeSource = feature.properties?.routeSource || "OpenStreetMap ferry network";
  } else if (mode === "train" && osmTransit) {
    routeSource = feature.properties?.routeSource || "OpenStreetMap rail network";
  } else if (mode === "train") {
    routeSource = "planned rail leg";
  } else if (mode === "fly") {
    routeSource = "direct great-circle flight path";
  } else if (mode === "hike" && catalogTrail) {
    routeSource = feature.properties?.routeSource || "OpenStreetMap hiking trail";
  } else if (mode === "hike") {
    routeSource = "OpenStreetMap footpaths via OSRM";
  }

  return {
    ...feature,
    geometry: {
      type: "LineString",
      coordinates: snapped
    },
    properties: {
      ...feature.properties,
      distanceKm: Math.round(distanceKm * 10) / 10,
      routeSource
    }
  };
}

export function lineFeatureKey(feature) {
  const props = feature?.properties || {};
  return `${props.name || ""}:${props.mode || "drive"}`;
}

async function mapWithConcurrency(items, mapper, concurrency = 4) {
  if (!items.length) {
    return [];
  }

  const results = new Array(items.length);
  let nextIndex = 0;

  const worker = async () => {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await mapper(items[index], index);
    }
  };

  const workers = Array.from({ length: Math.min(concurrency, items.length) }, () => worker());
  await Promise.all(workers);
  return results;
}

export async function enrichTripLineFeatures(features, { onProgress, concurrency = 4 } = {}) {
  const lines = features.filter((f) => f?.geometry?.type === "LineString");
  let completed = 0;

  const enriched = await mapWithConcurrency(
    lines,
    async (line) => {
      const result = await enrichLineFeature(line);
      completed += 1;
      onProgress?.(completed, lines.length, line?.properties?.name);
      return result;
    },
    concurrency
  );

  const byRef = new Map(enriched.map((f) => [lineFeatureKey(f), f]));

  return features.map((f) => {
    if (f?.geometry?.type !== "LineString") {
      return f;
    }
    return byRef.get(lineFeatureKey(f)) || f;
  });
}
