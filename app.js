import L from "leaflet";
import { marked } from "marked";
import {
  buildEmojiHeroHtml,
  buildHighlightsCarouselHtml,
  buildMediaCarouselHtml,
  buildPopupHeroImageTag,
  dedupePhotoEntries,
  emojiForPlace,
  escapeAttr,
  escapeHtml,
  initHighlightsCarousels,
  initMediaCarousels,
  normalizePhotoEntries,
  photoFingerprint,
  setupMediaLightbox
} from "./media.js";
import { convertItineraryHtmlToAud, formatAud } from "./currency.js";
import {
  enrichTripLineFeatures,
  ferryRouteFromCatalog,
  lineFeatureKey,
  loadFerryRoutesCatalog,
  loadTransitRoutesCatalog,
  normalizeLineFeature,
  refineHikeTrailGeometry,
  transitRouteFromCatalog
} from "./routing.js";
import { enhanceItineraryContent, decorateItineraryPlaces } from "./itinerary-render.js";
import {
  loadCityRegion,
  fetchCityFeatures,
  fetchCityById,
  lookupCityByName,
  fetchCountries,
  fetchCountryPopStats,
  searchPlaces,
  getCityDetail
} from "./cities.js";
import {
  loadHikeRegion,
  fetchHikeFeatures,
  fetchHikeById,
  searchHikes
} from "./hikes.js";
import { loadParkRegion, fetchParkFeatures, fetchParkById, searchParks } from "./parks.js";
import { fetchCountryDossier } from "./country-dossier.js";
import { createSharedJourney, fetchSharedJourney, isJourneyCode } from "./journey-codes.js";
import {
  addMintedJourney,
  clearJourneyDraft,
  readJourneyDraft,
  readMintedJourneys,
  removeMintedJourney,
  writeJourneyDraft,
} from "./journey-storage.js";
import { loadSeasonHints, buildTimeOfYearHtml } from "./seasons.js";
import {
  getFavorites,
  isFavorite,
  toggleFavorite,
  subscribeFavorites,
} from "./favorites.js";
import { loadPoiRegion, fetchPoiFeatures, fetchPoiById, searchPois } from "./poi.js";
import { inject as injectVercelAnalytics } from "@vercel/analytics";
import { injectSpeedInsights } from "@vercel/speed-insights";

/* Vercel Analytics + Speed Insights.
 * Both packages are safe no-ops in local/dev (they auto-detect the
 * VERCEL_ENV and only send beacons when the site is served from Vercel),
 * so we can call them unconditionally. */
injectVercelAnalytics();
injectSpeedInsights();

const DEFAULT_MAP_VIEW = { center: [52, 15], zoom: 4 };

const map = L.map("map", {
  zoomControl: false,
  scrollWheelZoom: true
}).setView(DEFAULT_MAP_VIEW.center, DEFAULT_MAP_VIEW.zoom);

L.control.zoom({ position: "bottomright" }).addTo(map);
L.control.scale({ position: "bottomleft", imperial: false, maxWidth: 140 }).addTo(map);

map.createPane("routeGlow");
map.getPane("routeGlow").style.zIndex = "390";

map.createPane("routeLine");
map.getPane("routeLine").style.zIndex = "420";

map.createPane("countryRegions");
map.getPane("countryRegions").style.zIndex = "370";

map.createPane("citiesCatalog");
map.getPane("citiesCatalog").style.zIndex = "500";

map.createPane("hikeRouteGlow");
map.getPane("hikeRouteGlow").style.zIndex = "475";

map.createPane("hikeRouteActive");
map.getPane("hikeRouteActive").style.zIndex = "485";

map.createPane("hikesCatalog");
map.getPane("hikesCatalog").style.zIndex = "510";

map.createPane("parksCatalog");
map.getPane("parksCatalog").style.zIndex = "505";

map.createPane("poisCatalog");
map.getPane("poisCatalog").style.zIndex = "507";

map.createPane("routeMarkers");
map.getPane("routeMarkers").style.zIndex = "650";

const mapEl = document.getElementById("map");

map.createPane("basemapOverlay");
map.getPane("basemapOverlay").style.zIndex = "350";

const basemapConfig = {
  voyager: { label: "Atlas", hint: "Balanced terrain and labels" },
  streets: { label: "Streets", hint: "OpenStreetMap detail" },
  light: { label: "Light", hint: "Minimal light base" },
  dark: { label: "Night", hint: "Dark base for contrast" },
  satellite: { label: "Satellite", hint: "Aerial imagery" },
  terrain: { label: "Terrain", hint: "Topographic shading" }
};

const overlayConfig = {
  labels: { label: "Labels", hint: "Place names on imagery" },
  transit: { label: "Transit", hint: "Public transport lines" }
};

const basemapLayers = {
  voyager: L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 19
  }),
  streets: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19
  }),
  light: L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 19
  }),
  dark: L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 19
  }),
  satellite: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles &copy; Esri",
    maxZoom: 19
  }),
  terrain: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    attribution: "Map data: &copy; OpenStreetMap, SRTM | Style: &copy; OpenTopoMap",
    maxZoom: 17
  })
};

const overlayLayers = {
  labels: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Labels &copy; Esri",
    pane: "basemapOverlay",
    maxZoom: 19
  }),
  transit: L.tileLayer("https://{s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png", {
    attribution: "Overlay &copy; OpenRailwayMap &copy; OpenStreetMap",
    pane: "basemapOverlay",
    maxZoom: 19,
    opacity: 0.85
  })
};

let activeBasemapLayer = null;

const trailRouteStyle = {
  line: { color: "#ea580c", weight: 5, opacity: 0.95, dashArray: "" },
  glow: { color: "#c2410c", weight: 12, opacity: 0.35, dashArray: "" }
};

const modeConfig = {
  drive: { label: "Drive", color: "#0f766e", dashArray: "" },
  train: { label: "Train", color: "#1d4ed8", dashArray: "7 5" },
  hike: { label: "Trail", color: trailRouteStyle.line.color, dashArray: "" },
  ferry: { label: "Ferry", color: "#0284c7", dashArray: "2 8" },
  fly: { label: "Flight", color: "#f97316", dashArray: "11 8" }
};

const continentConfig = {
  all: { label: "All" },
  europe: { label: "Europe" },
  asia: { label: "Asia" }
};

let placeDetails = {};
let lineEntries = [];
let pointEntries = [];
let cityCatalog = null;
let cityCountryPopStats = null;
let cityCatalogLayer = null;
let cityCatalogMarkersInView = new Map();
let cityCatalogFetchId = 0;
let cityCatalogRefreshTimer = null;
let countryRegionsGeo = null;
let countryRegionsLayer = null;
let mapSearchCountries = [];
let hikeCatalog = null;
let hikeCatalogLayer = null;
let hikeCatalogMarkersInView = new Map();
let hikeCatalogFetchId = 0;
let hikeCatalogRefreshTimer = null;

let parkCatalog = null;
let parkCatalogLayer = null;
let parkCatalogMarkersInView = new Map();
let parkCatalogFetchId = 0;
let parkCatalogRefreshTimer = null;
let poiCatalog = null;
let poiCatalogLayer = null;
let poiCatalogMarkersInView = new Map();
let poiCatalogFetchId = 0;
let poiCatalogRefreshTimer = null;
let activePoiCatalogId = null;
let activeHikeRouteLayer = null;
let activeHikeRouteGlowLayer = null;
let activeHikeEndpointsLayer = null;
let hikeDetailFetchToken = 0;
let state = {
  basemap: "voyager",
  overlays: { labels: false, transit: false },
  modes: { drive: true, train: true, hike: true, ferry: true, fly: true },
  trips: [],
  selectedTrip: null,
  continentFilter: "all",
  activeView: "map",
  exploreCities: false,
  exploreParks: false,
  exploreHikes: false,
  explorePoi: false,
  welcomeDismissed: false,
  mapExploreHintDismissed: false
};
let _overlayHideTimeout = null;
const tripGeojsonCache = new Map();
const tripPrefetchInFlight = new Map();
let tripEnrichGeneration = 0;

const layoutRoot = document.getElementById("layoutRoot");
const tripOverlay = document.getElementById("tripOverlay");
const tripMenuGrid = document.getElementById("tripMenuGrid");
const openJourneysMenuButton = document.getElementById("openJourneysMenuButton");
const closeTripMenuButton = document.getElementById("closeTripMenuButton");
const hudNav = document.getElementById("hudNav");
const journeysMenuHint = document.getElementById("journeysMenuHint");
const itineraryPanel = document.getElementById("itineraryPanel");
const welcomeOverlay = document.getElementById("welcomeOverlay");
const exploreModeBtn = document.getElementById("exploreModeBtn");
const mapHintBar = document.getElementById("mapHintBar");
const journeyEmptyState = document.getElementById("journeyEmptyState");
const tripQuickStats = document.getElementById("tripQuickStats");

const VIEW_IDS = ["map", "story", "stops"];

function hasActiveJourney() {
  return Boolean(state.selectedTrip);
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

let hudLayoutRestoreTimer = null;

/** Detail overlays (city / trail sheets) toggle HUD layout on both body and #layoutRoot. */
function setDetailOverlayClass(className, open) {
  document.body.classList.toggle(className, open);
  layoutRoot?.classList.toggle(className, open);
}

function restoreHudLayoutAfterDetailOverlay() {
  if (hudLayoutRestoreTimer) {
    clearTimeout(hudLayoutRestoreTimer);
    hudLayoutRestoreTimer = null;
  }
  const run = () => {
    syncStoryPanelLayout();
    updateLayoutInsets();
    syncMapPopupStacking();
  };
  requestAnimationFrame(() => {
    run();
    requestAnimationFrame(run);
  });
  hudLayoutRestoreTimer = window.setTimeout(() => {
    hudLayoutRestoreTimer = null;
    run();
  }, 360);
}

function updateHudNavIndicator() {
  const indicator = document.getElementById("hudNavIndicator");
  const active = hudNav?.querySelector('.hud-nav-item[data-active="true"]');
  if (!indicator || !active) {
    return;
  }

  indicator.style.width = `${active.offsetWidth}px`;
  indicator.style.transform = `translateX(${active.offsetLeft}px)`;
}

function setActiveView(view, options = {}) {
  const { silent = false } = options;
  if (!VIEW_IDS.includes(view)) {
    return;
  }

  if (!hasActiveJourney() && (view === "story" || view === "stops")) {
    if (!silent) {
      renderJourneyRequiredToast(view);
    }
    view = "map";
  }

  state.activeView = view;

  hudNav?.querySelectorAll(".hud-nav-item").forEach((button) => {
    const isActive = button.dataset.view === view;
    button.dataset.active = String(isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });

  requestAnimationFrame(() => {
    updateHudNavIndicator();
    updateLayoutInsets();
  });

  itineraryPanel?.classList.toggle("view-story-focus", view === "story" || view === "stops");
  itineraryPanel?.classList.toggle("journey-panel--view-story", view === "story");
  itineraryPanel?.classList.toggle("journey-panel--view-stops", view === "stops");
  itineraryPanel?.classList.toggle("journey-panel--view-map", view === "map");

  if (silent) {
    return;
  }

  const stopsPanel = document.getElementById("stopsPanel");

  switch (view) {
    case "map":
      closeTripOverlay();
      if (stopsPanel) {
        stopsPanel.hidden = true;
      }
      break;
    case "story":
      closeTripOverlay();
      setPanelCollapsed(false);
      if (stopsPanel) {
        stopsPanel.hidden = true;
      }
      focusStoryPanel();
      break;
    case "stops":
      closeTripOverlay();
      setPanelCollapsed(false);
      if (stopsPanel) {
        stopsPanel.hidden = false;
      }
      focusStopsPanel();
      break;
    default:
      break;
  }
}

function focusStoryPanel() {
  const content = document.getElementById("itineraryContent");
  content?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function focusStopsPanel() {
  document.getElementById("stopsPanel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function updateJourneysMenuHint() {
  if (!journeysMenuHint) {
    return;
  }

  const count = state.trips.length;
  if (!hasActiveJourney()) {
    journeysMenuHint.textContent = count === 1 ? "1 sample route" : `${count} sample routes`;
    return;
  }

  const trip = state.trips.find((item) => item.key === state.selectedTrip);
  journeysMenuHint.textContent = trip?.title || "Clear from map";
}

function updateJourneysMenuButton() {
  const btn = openJourneysMenuButton;
  if (!btn) {
    return;
  }

  const labelEl = btn.querySelector(".journeys-menu-label");
  const iconEl = btn.querySelector(".journeys-menu-icon");
  const active = hasActiveJourney();
  const trip = state.trips.find((item) => item.key === state.selectedTrip);

  btn.classList.toggle("journeys-menu-btn--deselect", active);
  btn.dataset.journeyAction = active ? "deselect" : "browse";

  if (active) {
    if (labelEl) {
      labelEl.textContent = "Deselect";
    }
    if (iconEl) {
      iconEl.textContent = "✕";
    }
    btn.title = "Remove this journey from the map";
    btn.setAttribute("aria-label", trip ? `Deselect journey: ${trip.title}` : "Deselect journey");
    btn.removeAttribute("aria-haspopup");
    btn.removeAttribute("aria-controls");
  } else {
    if (labelEl) {
      labelEl.textContent = "Journeys";
    }
    if (iconEl) {
      iconEl.textContent = "🧭";
    }
    btn.title = "Browse and open a journey";
    btn.setAttribute("aria-label", "Browse and open a journey");
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-controls", "tripOverlay");
  }
}

function deselectJourney() {
  if (!hasActiveJourney()) {
    return;
  }

  closeHikeStory();
  closePlaceStory();

  tripEnrichGeneration += 1;
  state.selectedTrip = null;
  clearTripLayers();
  layoutRoot?.classList.remove("is-trip-loading");
  map.closePopup();
  renderEmptyJourneyPanel();
  setPanelCollapsed(true);
  renderTripMenu();
  renderHudJourneyStrip();
  syncMapPopupStacking();
  requestAnimationFrame(updateLayoutInsets);
  setTimeout(() => map.invalidateSize(), 260);
}

function updateHudJourneyState() {
  const titleEl = document.getElementById("hudTripName");
  const subtitleEl = document.getElementById("hudTripSubtitle");
  const trip = state.trips.find((item) => item.key === state.selectedTrip);

  layoutRoot?.classList.toggle("map-stage--no-journey", !hasActiveJourney());
  document.body.classList.toggle("no-journey-selected", !hasActiveJourney());

  if (!hasActiveJourney()) {
    if (titleEl) {
      const exploring =
        state.exploreCities || state.exploreParks || state.exploreHikes || state.explorePoi;
      titleEl.textContent = exploring ? "Explore mode" : "Pick a journey or explore";
    }
    if (subtitleEl) {
      const parts = [];
      if (state.exploreCities) {
        parts.push("cities");
      }
      if (state.exploreHikes) {
        parts.push("trails");
      }
      if (state.explorePoi) {
        parts.push("landmarks");
      }
      subtitleEl.textContent = parts.length
        ? `${parts.join(" & ")} on the map — pan to browse, tap for details`
        : "Browse sample routes or discover cities, parks, trails, and landmarks on the map";
    }
    return;
  }

  if (trip && titleEl) {
    titleEl.textContent = trip.title;
  }
  if (subtitleEl && trip?.region) {
    subtitleEl.textContent = trip.region;
  } else if (subtitleEl) {
    subtitleEl.textContent = "Journey loaded — use Story or Stops for details";
  }
}

function syncHudNavAvailability() {
  hudNav?.querySelectorAll('.hud-nav-item[data-view="story"], .hud-nav-item[data-view="stops"]').forEach((button) => {
    const disabled = !hasActiveJourney();
    button.disabled = disabled;
    button.setAttribute("aria-disabled", String(disabled));
    button.title = disabled ? "Select a journey first" : "";
  });
}

function renderJourneyRequiredToast(view) {
  const label = view === "stops" ? "Stops" : "Story";
  const hint = document.getElementById("mapHintText");
  if (mapHintBar && hint) {
    hint.textContent = `${label} is available after you open a journey from the library.`;
    mapHintBar.hidden = false;
    layoutRoot?.classList.add("map-hint-visible");
    requestAnimationFrame(updateLayoutInsets);
    window.setTimeout(() => {
      if (!state.exploreCities) {
        return;
      }
      hint.textContent = "Pan and zoom to discover cities. Tap a marker for details.";
    }, 4200);
  }
}

function showWelcomeOverlay() {
  if (!welcomeOverlay || state.welcomeDismissed) {
    return;
  }
  welcomeOverlay.classList.remove("hidden");
  welcomeOverlay.classList.add("open");
  document.body.classList.add("welcome-open");
  requestAnimationFrame(updateLayoutInsets);
}

function dismissWelcomeOverlay() {
  if (!welcomeOverlay) {
    return;
  }
  state.welcomeDismissed = true;
  welcomeOverlay.classList.remove("open");
  document.body.classList.remove("welcome-open");
  window.setTimeout(() => {
    welcomeOverlay.classList.add("hidden");
    requestAnimationFrame(updateLayoutInsets);
  }, 320);
}

function renderEmptyJourneyPanel() {
  itineraryPanel?.classList.add("journey-panel--empty");
  journeyEmptyState?.removeAttribute("hidden");

  const titleEl = document.getElementById("tripTitle");
  const descEl = document.getElementById("tripDescription");
  const regionEl = document.getElementById("tripRegion");
  const highlightsEl = document.getElementById("tripHighlights");
  const gallery = document.getElementById("tripGallery");
  const content = document.getElementById("itineraryContent");
  const stopsPanel = document.getElementById("stopsPanel");

  if (titleEl) {
    titleEl.textContent = "No journey selected";
  }
  if (descEl) {
    descEl.textContent = "Explore the map or open a journey from the library to see routes, stories, and stops.";
  }
  regionEl?.setAttribute("hidden", "");
  highlightsEl?.setAttribute("hidden", "");
  tripQuickStats?.setAttribute("hidden", "");
  gallery?.setAttribute("hidden", "");
  content?.setAttribute("hidden", "");
  stopsPanel?.setAttribute("hidden", "");

  const list = document.getElementById("stopsList");
  if (list) {
    list.innerHTML = "";
  }
  if (content) {
    content.innerHTML = "";
  }

  updateHudJourneyState();
  syncHudNavAvailability();
  syncRouteControlsVisibility();
}

function syncRouteControlsVisibility() {
  const routeGroup = document.getElementById("routeLegend")?.closest(".control-group");
  if (routeGroup) {
    routeGroup.hidden = !hasActiveJourney();
  }
}

function enterExploreMode(options = {}) {
  const { dismissWelcome = true, flyToEurope = true } = options;

  if (!state.exploreCities) {
    setExploreCities(true);
  }
  if (!state.exploreParks) {
    setExploreParks(true);
  }
  if (!state.exploreHikes) {
    setExploreHikes(true);
  }
  if (!state.explorePoi) {
    setExplorePoi(true);
  }

  if (dismissWelcome) {
    dismissWelcomeOverlay();
  }

  setActiveView("map", { silent: true });
  // Keep the itinerary panel open when a journey is loaded so city/trail detail modals stack on top.
  if (!hasActiveJourney()) {
    setPanelCollapsed(true);
  }

  if (flyToEurope && !hasActiveJourney()) {
    map.flyTo(DEFAULT_MAP_VIEW.center, DEFAULT_MAP_VIEW.zoom, { duration: 0.9 });
  }

  showMapExploreHint();
  updateHudJourneyState();
}

function showMapExploreHint(options = {}) {
  const { force = false } = options;
  if (!mapHintBar || (!force && state.mapExploreHintDismissed)) {
    return;
  }
  const hint = document.getElementById("mapHintText");
  if (hint) {
    hint.textContent =
      "Zoom out for country outlines. Zoom in, then tap a city, park, trail, or landmark marker for details.";
  }
  mapHintBar.hidden = false;
  layoutRoot?.classList.add("map-hint-visible");
  requestAnimationFrame(updateLayoutInsets);
}

function hideMapExploreHint() {
  state.mapExploreHintDismissed = true;
  if (mapHintBar) {
    mapHintBar.hidden = true;
  }
  layoutRoot?.classList.remove("map-hint-visible");
  requestAnimationFrame(() => {
    updateLayoutInsets();
    map.invalidateSize();
  });
}

function setupMapHintBar() {
  if (!mapHintBar || mapHintBar.dataset.hintBound === "true") {
    return;
  }
  mapHintBar.dataset.hintBound = "true";

  mapHintBar.addEventListener("click", (event) => {
    if (!event.target.closest("#mapHintDismiss")) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    hideMapExploreHint();
  });

  mapHintBar.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    if (!event.target.closest("#mapHintDismiss")) {
      return;
    }
    event.preventDefault();
    hideMapExploreHint();
  });
}

function getFilteredTrips() {
  if (state.continentFilter === "all") {
    return state.trips;
  }
  return state.trips.filter((trip) => trip.continent === state.continentFilter);
}

function renderContinentFilters() {
  const container = document.getElementById("continentFilters");
  if (!container) {
    return;
  }

  const continents = [
    "all",
    ...new Set(state.trips.map((trip) => trip.continent).filter(Boolean))
  ].sort((a, b) => {
    if (a === "all") {
      return -1;
    }
    if (b === "all") {
      return 1;
    }
    return a.localeCompare(b);
  });

  container.innerHTML = continents
    .map((key) => {
      const active = state.continentFilter === key;
      const label = continentConfig[key]?.label || key;
      const count =
        key === "all"
          ? state.trips.length
          : state.trips.filter((trip) => trip.continent === key).length;
      return `
        <button
          type="button"
          class="continent-chip"
          data-continent="${key}"
          data-active="${String(active)}"
          aria-pressed="${String(active)}"
        >
          ${label}
          <span class="continent-chip-count">${count}</span>
        </button>
      `;
    })
    .join("");
}

function renderHudJourneyStrip() {
  updateJourneysMenuHint();
  updateJourneysMenuButton();
}

function renderStopsList(pointFeatures) {
  const list = document.getElementById("stopsList");
  if (!list) {
    return;
  }

  list.innerHTML = pointFeatures
    .map((feature, index) => {
      const props = feature.properties || {};
      const name = props.name || "Stop";
      const country = getPlaceDetail(name).country || props.country || "";
      const meta = [props.day ? `Day ${props.day}` : "", country].filter(Boolean).join(" · ");
      const safeName = name.replace(/"/g, "&quot;");
      const details = getPlaceDetail(name);
      const photos = getPlacePhotos(name);
      const photo = photos[0]?.url;
      const tagline = placeTagline(details);
      const flagUrl = countryFlagUrl(country);
      const flagHtml = flagUrl
        ? `<img class="dest-stop-card__flag" src="${escapeHtml(flagUrl)}" alt="" width="14" height="14" loading="lazy" referrerpolicy="no-referrer" />`
        : "";

      const photoImg = photo
        ? `<img class="dest-stop-card__media-img" src="${escapeHtml(photo)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.parentElement?.classList.add('is-loaded')" onerror="this.remove()" />`
        : "";
      return `
        <button
          type="button"
          class="dest-stop-card dest-stop-card--row"
          data-stop-name="${safeName}"
          style="animation-delay:${index * 35}ms"
        >
          <div class="dest-stop-card__media">
            ${photoImg}
            <div class="dest-stop-card__media-fallback" aria-hidden="true"></div>
            <div class="dest-stop-card__gradient"></div>
            ${flagHtml}
            ${photos.length > 1 ? `<span class="dest-stop-card__photos">${photos.length} photos</span>` : ""}
          </div>
          <div class="dest-stop-card__body">
            <span class="dest-stop-card__name">${escapeHtml(name)}</span>
            <span class="dest-stop-card__tagline">${escapeHtml(tagline)}</span>
            <span class="dest-stop-card__meta">${escapeHtml(meta || "Route stop")}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function flyToStop(name) {
  const entry = pointEntries.find((item) => item.props?.name === name);
  if (!entry) {
    return;
  }

  const latlng = entry.marker.getLatLng();
  map.flyTo(latlng, Math.max(map.getZoom(), 11), { duration: 1.1 });
  window.setTimeout(() => entry.marker.openPopup(), 380);
}

function animateHudTitle(text) {
  const titleEl = document.getElementById("hudTripName");
  if (!titleEl) {
    return;
  }

  titleEl.classList.add("is-swapping");
  window.setTimeout(() => {
    titleEl.textContent = text;
    titleEl.classList.remove("is-swapping");
  }, 160);
}

function setupHudNav() {
  hudNav?.querySelectorAll(".hud-nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      const view = button.dataset.view;
      if (view === state.activeView) {
        return;
      }
      setActiveView(view);
    });
  });

  document.getElementById("stopsList")?.addEventListener("click", (event) => {
    const stopButton = event.target.closest("button[data-stop-name]");
    if (!stopButton) {
      return;
    }
    const name = stopButton.dataset.stopName;
    flyToStop(name);
    const entry = pointEntries.find((item) => item.props?.name === name);
    openPlaceStory(name, entry?.props || {});
  });

  window.addEventListener("resize", () => {
    updateHudNavIndicator();
    updateLayoutInsets();
  });
  requestAnimationFrame(() => {
    updateHudNavIndicator();
    updateLayoutInsets();
  });
}

function classifyLineSection(feature) {
  if (feature?.properties?.section) {
    return feature.properties.section;
  }

  const mode = feature?.properties?.mode || "drive";
  if (mode === "ferry" || mode === "fly") {
    return "optionalLinks";
  }
  return "core";
}

function classifyPointSection(feature) {
  return feature?.properties?.section || "core";
}

function pathGlowStyleByMode(mode, props = {}) {
  if (mode === "hike" && props.hikeId) {
    return {
      color: trailRouteStyle.glow.color,
      weight: trailRouteStyle.glow.weight,
      opacity: trailRouteStyle.glow.opacity,
      dashArray: trailRouteStyle.glow.dashArray,
      lineCap: "round",
      lineJoin: "round"
    };
  }
  return {
    color: modeConfig[mode]?.color || "#000000",
    weight: mode === "fly" ? 6 : 9,
    opacity: mode === "fly" ? 0.22 : 0.32,
    dashArray: modeConfig[mode]?.dashArray || "",
    lineCap: "round",
    lineJoin: "round"
  };
}

function pathStyleByMode(mode, props = {}) {
  if (mode === "hike" && props.hikeId) {
    return {
      color: trailRouteStyle.line.color,
      weight: trailRouteStyle.line.weight,
      opacity: trailRouteStyle.line.opacity,
      dashArray: trailRouteStyle.line.dashArray,
      lineCap: "round",
      lineJoin: "round"
    };
  }
  return {
    color: modeConfig[mode]?.color || "#000000",
    weight: mode === "fly" ? 2.5 : 3.5,
    opacity: 0.95,
    dashArray: modeConfig[mode]?.dashArray || "",
    lineCap: "round",
    lineJoin: "round"
  };
}

const JOURNEY_CITY_BY_NAME = new Set([
  "dubrovnik",
  "mostar",
  "herceg novi",
  "granada",
  "split",
  "bari",
  "kotor",
  "bar",
  "naples",
  "rome",
  "zadar",
  "hvar"
]);

function journeyStopType(props = {}) {
  const raw = props.stopType || "city";
  const name = (props.name || "").trim().toLowerCase();
  if (raw === "heritage" && JOURNEY_CITY_BY_NAME.has(name)) {
    return "city";
  }
  return raw;
}

function stopColor(stopType) {
  const colors = {
    start: "#0f172a",
    end: "#be123c",
    city: "#1d4ed8",
    park: "#166534",
    heritage: "#9333ea"
  };
  return colors[stopType] || "#1d4ed8";
}

function poiCategoryLabel(category) {
  const labels = {
    fortress: "Fortress",
    palace: "Palace",
    cathedral: "Cathedral",
    monastery: "Monastery",
    bridge: "Bridge",
    archaeological: "Archaeological site",
    mountain: "Mountain",
    monument: "Monument",
    museum: "Museum",
    heritage: "Heritage site",
    landmark: "Landmark"
  };
  return labels[category] || "Point of interest";
}

function parkCategoryLabel(category) {
  const labels = {
    "national-park": "National park",
    "marine-park": "Marine park",
    "coastal-park": "Coastal park",
    "lake-park": "Lake park",
    "mountain-park": "Mountain park",
    "forest-park": "Forest park",
    "archaeological-park": "Archaeological park",
    geopark: "Geopark",
    "nature-reserve": "Nature reserve"
  };
  return labels[category] || "Nature & parks";
}

const CITY_CATEGORY_KEYS = new Set([
  "capital", "metropolis", "city", "town", "village", "hamlet"
]);

const PARK_CATEGORY_KEYS = new Set([
  "national-park", "marine-park", "coastal-park", "lake-park",
  "mountain-park", "forest-park", "archaeological-park", "geopark",
  "nature-reserve"
]);

const POI_CATEGORY_KEYS = new Set([
  "fortress", "palace", "cathedral", "monastery", "bridge",
  "archaeological", "mountain", "monument", "museum", "heritage",
  "landmark"
]);

function cityCategoryLabel(category, locale) {
  const base = {
    capital: "Capital",
    metropolis: "Metropolis",
    city: "City",
    town: "Town",
    village: "Village",
    hamlet: "Hamlet"
  }[category] || "City";
  const prefix = {
    coastal: "Coastal",
    island: "Island",
    mountain: "Mountain",
    riverside: "Riverside"
  }[locale];
  if (!prefix) {
    return base;
  }
  if (category === "capital") {
    return `${prefix} capital`;
  }
  return `${prefix} ${base.toLowerCase()}`;
}

function modeLabel(mode) {
  return modeConfig[mode]?.label || mode;
}

function getPlaceDetail(name) {
  const direct = placeDetails[name];
  if (direct) {
    return direct;
  }

  const normalized = name.toLowerCase();
  const fuzzyKey = Object.keys(placeDetails).find((key) => {
    const keyNorm = key.toLowerCase();
    return keyNorm.includes(normalized) || normalized.includes(keyNorm);
  });

  if (fuzzyKey) {
    return placeDetails[fuzzyKey];
  }

  return {
    general: "Destination stop on the selected journey route.",
    activities: ["Orientation walk", "Scenic viewpoint", "Local food stop"],
    tips: [],
    itinerary: "Follow day sequencing in the itinerary panel for this location.",
    photos: []
  };
}

function getPlacePhoto(name) {
  const entries = normalizePhotoEntries(getPlaceDetail(name).photos);
  return entries[0]?.url || "";
}

function getPlacePhotos(name) {
  return normalizePhotoEntries(getPlaceDetail(name).photos);
}

function countryColorFromCc(cc, { lightness = 58, saturation = 50, alpha = 1 } = {}) {
  const code = String(cc || "EU").toUpperCase();
  let hash = 0;
  for (let i = 0; i < code.length; i += 1) {
    hash = code.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsla(${hue}, ${saturation}%, ${lightness}%, ${alpha})`;
}

function countryBorderColor(cc) {
  return countryColorFromCc(cc, { lightness: 42, saturation: 55, alpha: 0.75 });
}

function styleCountryRegion(feature) {
  const cc = feature.properties?.cc;
  return {
    fillColor: countryColorFromCc(cc, { lightness: 62, saturation: 48, alpha: 1 }),
    fillOpacity: 0.16,
    color: countryBorderColor(cc),
    weight: 1,
    opacity: 0.55
  };
}

async function loadCountryRegionsGeo() {
  if (countryRegionsGeo) {
    return countryRegionsGeo;
  }
  const response = await fetch("./Trip/geo/europe-countries.geojson");
  if (!response.ok) {
    throw new Error("Could not load country borders.");
  }
  countryRegionsGeo = await response.json();
  return countryRegionsGeo;
}

function syncCountryRegionsLayer() {
  const zoom = map.getZoom();
  const showBorders =
    (state.exploreCities || state.exploreParks || state.exploreHikes || state.explorePoi) && zoom <= 8;

  if (!showBorders) {
    if (countryRegionsLayer && map.hasLayer(countryRegionsLayer)) {
      map.removeLayer(countryRegionsLayer);
    }
    return;
  }

  if (!countryRegionsLayer || !countryRegionsGeo) {
    return;
  }

  if (!map.hasLayer(countryRegionsLayer)) {
    countryRegionsLayer.addTo(map);
  }

  countryRegionsLayer.eachLayer((layer) => {
    if (layer.feature) {
      layer.setStyle(styleCountryRegion(layer.feature));
    }
  });
}

async function buildCountryRegionsLayer() {
  try {
    const geo = await loadCountryRegionsGeo();
    if (countryRegionsLayer) {
      map.removeLayer(countryRegionsLayer);
    }
    countryRegionsLayer = L.geoJSON(geo, {
      pane: "countryRegions",
      style: styleCountryRegion,
      interactive: false
    });
    syncCountryRegionsLayer();
  } catch (error) {
    console.warn("Country borders not loaded:", error);
  }
}

async function initCountryBorders() {
  try {
    await buildCountryRegionsLayer();
  } catch (error) {
    console.warn("Country borders not loaded:", error);
  }
}

const COUNTRY_FLAG_CODES = {
  Italy: "it",
  Montenegro: "me",
  Croatia: "hr",
  "Bosnia and Herzegovina": "ba",
  France: "fr",
  Spain: "es",
  Gibraltar: "gi",
  Georgia: "ge",
  Armenia: "am",
  Vietnam: "vn",
  Japan: "jp",
  "United Kingdom": "gb",
  Ireland: "ie",
  Portugal: "pt",
  Germany: "de",
  Netherlands: "nl",
  Belgium: "be",
  Switzerland: "ch",
  Austria: "at",
  "Czech Republic": "cz",
  Poland: "pl",
  Hungary: "hu",
  Romania: "ro",
  Bulgaria: "bg",
  Greece: "gr",
  Serbia: "rs",
  Slovenia: "si",
  Sweden: "se",
  Denmark: "dk",
  Norway: "no",
  Finland: "fi",
  Iceland: "is",
  Estonia: "ee",
  Latvia: "lv",
  Lithuania: "lt",
  Ukraine: "ua",
  Turkey: "tr",
  Russia: "ru",
  Albania: "al",
  "North Macedonia": "mk",
  Luxembourg: "lu",
  Monaco: "mc",
  Malta: "mt"
};

function countryFlagUrl(country) {
  const code = COUNTRY_FLAG_CODES[country];
  return code ? `https://flagcdn.com/w40/${code}.png` : "";
}

function completeReadablePhrase(text, maxLen = 88) {
  let t = String(text || "").trim().replace(/\s+/g, " ");
  if (!t) {
    return "";
  }
  if (t.endsWith("…")) {
    t = t.slice(0, -1).trim().replace(/[,;—]$/, "");
  }
  if (t.length <= maxLen) {
    return /[.!?]$/.test(t) ? t : `${t}.`;
  }
  const head = t.slice(0, maxLen);
  for (const sep of [". ", "! ", "? "]) {
    const idx = head.lastIndexOf(sep);
    if (idx >= maxLen * 0.45) {
      return t.slice(0, idx + 1).trim();
    }
  }
  const comma = head.lastIndexOf(", ");
  if (comma >= maxLen * 0.45) {
    const line = t.slice(0, comma).trim();
    return /[.!?]$/.test(line) ? line : `${line}.`;
  }
  const space = window.lastIndexOf(" ");
  const line = (space >= 40 ? t.slice(0, space) : window).trim().replace(/[,;—]$/, "");
  return /[.!?]$/.test(line) ? line : `${line}.`;
}

const incompletePhraseTail =
  /\b(?:a|an|the|and|or|with|in|on|at|to|for|of|by|as|its|their|is|are|was|were)\s*\.?$/i;
const hangingPhraseTail =
  /\b(?:its|the|a|an|their|this|that|with|and|or)\s+[\w'-]+\.?$/i;
const brokenUnitTail = /\d[\d,]*\s+[a-z]{1,3}\.?$/i;

function isCompletePhrase(line, minLen = 24) {
  const t = String(line || "").trim();
  if (t.length < minLen) {
    return false;
  }
  if (incompletePhraseTail.test(t) || hangingPhraseTail.test(t) || brokenUnitTail.test(t)) {
    return false;
  }
  return true;
}

function formatHighlightLine(text) {
  const cleaned = String(text || "")
    .trim()
    .replace(/\s+/g, " ")
    .replace(/…$/, "")
    .trim();
  if (!cleaned) {
    return "";
  }
  if (cleaned.length <= 120) {
    const line = /[.!?]$/.test(cleaned) ? cleaned : `${cleaned}.`;
    return isCompletePhrase(line) ? line : "";
  }
  return "";
}

function placeTagline(details) {
  if (details.tagline) {
    return completeReadablePhrase(details.tagline, 88);
  }
  const firstActivity = details.activities?.[0];
  if (firstActivity) {
    return formatHighlightLine(firstActivity);
  }
  return completeReadablePhrase(details.general || "", 88);
}

function stopTypeLabel(stopType) {
  const labels = {
    city: "City stop",
    park: "Nature & parks",
    heritage: "Heritage site",
    start: "Trip start",
    end: "Trip end"
  };
  return labels[stopType] || "Destination";
}

function biodiversityStars(rating) {
  const n = Math.max(1, Math.min(5, Number(rating) || 3));
  return `${"★".repeat(n)}${"☆".repeat(5 - n)}`;
}

function buildPlaceStatsHtml(details, props) {
  const items = [];

  if (details.kind === "poi") {
    if (details.category_label || details.category) {
      items.push({
        icon: "🏛",
        label: "Type",
        value: details.category_label || poiCategoryLabel(details.category)
      });
    }
    if (details.popularity) {
      items.push({ icon: "⭐", label: "Notability", value: `Top ${details.popularity}% in catalog` });
    }
  } else if (details.kind === "park") {
    if (details.category) {
      items.push({ icon: "🏞", label: "Type", value: parkCategoryLabel(details.category) });
    }
    if (details.biodiversity) {
      items.push({
        icon: "🌿",
        label: "Biodiversity",
        value: biodiversityStars(details.biodiversity)
      });
    }
    if (details.area_label || details.area_km2) {
      items.push({
        icon: "📐",
        label: "Park size",
        value: details.area_label || `${Math.round(details.area_km2)} km²`
      });
    }
    if (details.stay) {
      items.push({ icon: "🛏", label: "Suggested stay", value: details.stay });
    }
    if (details.popularity) {
      items.push({ icon: "⭐", label: "Visitor appeal", value: `Top ${details.popularity}% in catalog` });
    }
  } else if (details.category || details.locale) {
    items.push({
      icon: "🏙",
      label: "Type",
      value: cityCategoryLabel(details.category, details.locale)
    });
    if (details.tier === "major" && details.popularity) {
      items.push({
        icon: "📊",
        label: "Popularity",
        value: details.popularity.label || `#${details.popularity.rank} in ${details.country}`
      });
      if (details.popularity.population) {
        items.push({
          icon: "👥",
          label: "Population",
          value: details.popularity.population
        });
      }
    } else if (details.pop > 0) {
      const pop = Number(details.pop);
      const label =
        pop >= 1_000_000 ? `${(pop / 1_000_000).toFixed(1).replace(/\.0$/, "")}M people` : `${Math.round(pop / 1000)}k people`;
      items.push({ icon: "👥", label: "Population", value: label });
    }
  } else if (details.tier === "major" && details.popularity) {
    items.push({
      icon: "📊",
      label: "Popularity",
      value: details.popularity.label || `#${details.popularity.rank} in ${details.country}`
    });
    if (details.popularity.population) {
      items.push({
        icon: "👥",
        label: "Population",
        value: details.popularity.population
      });
    }
  } else if (details.pop > 0) {
    const pop = Number(details.pop);
    const label =
      pop >= 1_000_000 ? `${(pop / 1_000_000).toFixed(1).replace(/\.0$/, "")}M people` : `${Math.round(pop / 1000)}k people`;
    items.push({ icon: "👥", label: "Population", value: label });
  }

  if (details.stay && details.kind !== "park") {
    items.push({ icon: "🛏", label: "Suggested stay", value: details.stay });
  }
  if (props.day) {
    items.push({ icon: "📅", label: "On your route", value: `Day ${props.day}` });
  }
  if (props.stopType) {
    const effectiveStop = journeyStopType(props);
    const hasRichType = Boolean(details.category || details.locale);
    const isPositional = effectiveStop === "start" || effectiveStop === "end";
    if (isPositional || !hasRichType) {
      items.push({ icon: "📍", label: "Stop type", value: stopTypeLabel(effectiveStop) });
    }
  }
  const photoCount = normalizePhotoEntries(details.photos).length;
  if (photoCount) {
    items.push({ icon: "📷", label: "Photos", value: `${photoCount} on map` });
  }

  return items
    .map(
      (item) => `
      <div class="dest-panel__stat">
        <dt class="dest-panel__stat-label"><span aria-hidden="true">${item.icon}</span> ${escapeHtml(item.label)}</dt>
        <dd class="dest-panel__stat-value">${escapeHtml(item.value)}</dd>
      </div>
    `
    )
    .join("");
}

function buildGoodToKnowHtml(details) {
  const rows = [
    { id: "tips", icon: "💡", title: "Good to know", items: details.tips || [] },
    { id: "itinerary", icon: "🗓", title: "Itinerary note", text: details.itinerary }
  ].filter((row) => row.text || (row.items && row.items.length));

  if (!rows.length) {
    return "";
  }

  return `
    <section class="dest-panel__know">
      <h3 class="dest-panel__section-title">Good to know</h3>
      <ul class="dest-panel__know-list">
        ${rows
          .map((row, index) => {
            const panelId = `dest-know-${row.id}`;
            const content = row.text
              ? `<p>${escapeHtml(row.text)}</p>`
              : `<ul>${row.items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
            return `
              <li class="dest-panel__know-item">
                <button type="button" class="dest-panel__know-btn" aria-expanded="${index === 0 ? "true" : "false"}" aria-controls="${panelId}">
                  <span class="dest-panel__know-icon" aria-hidden="true">${row.icon}</span>
                  <span class="dest-panel__know-title">${escapeHtml(row.title)}</span>
                  <svg class="dest-panel__know-chevron" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 16 16" aria-hidden="true">
                    <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" d="M5.85 13.15 11.15 8l-5.3-5.15" />
                  </svg>
                </button>
                <div id="${panelId}" class="dest-panel__know-panel${index === 0 ? " is-open" : ""}" ${index === 0 ? "" : "hidden"}>
                  ${content}
                </div>
              </li>
            `;
          })
          .join("")}
      </ul>
    </section>
  `;
}

function buildNearbyCitiesHtml(details) {
  const nearby = details.nearby || [];
  if (!nearby.length) {
    return "";
  }
  return `
    <section class="dest-panel__nearby">
      <h3 class="dest-panel__section-title">Cities to explore nearby</h3>
      <ul class="dest-panel__nearby-list">
        ${nearby
          .map(
            (city) => `
          <li>
            <button type="button" class="dest-panel__nearby-btn" data-nearby-city-id="${escapeAttr(city.id)}" data-nearby-city-name="${escapeAttr(city.name)}" data-nearby-country="${escapeAttr(city.country || "")}">
              <span class="dest-panel__nearby-name">${escapeHtml(city.name)}</span>
              <span class="dest-panel__nearby-meta">${escapeHtml(city.distanceKm ? `${city.distanceKm} km` : city.country || "")}</span>
            </button>
          </li>`
          )
          .join("")}
      </ul>
    </section>`;
}

function buildParkStoryBody(details) {
  const highlights = details.highlights || [];
  const carousel = buildHighlightsCarouselHtml(highlights, { title: details.name });
  const activityLines = (details.activities || [])
    .map((item) => formatHighlightLine(item))
    .filter(Boolean);

  return `
    ${
      carousel
        ? `
    <section class="dest-panel__highlights-section">
      <h3 class="dest-panel__section-title">Top things to do &amp; see</h3>
      ${carousel}
    </section>`
        : ""
    }
    ${
      activityLines.length
        ? `
    <section class="dest-panel__activities">
      <h3 class="dest-panel__section-title">Things to do</h3>
      <ul class="dest-panel__activity-list">
        ${activityLines.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>`
        : ""
    }
    ${buildTimeOfYearHtml(details.country || "")}
    ${buildGoodToKnowHtml(details)}
  `;
}

function buildMajorPlaceStoryBody(details) {
  const highlights = details.highlights || [];
  const carousel = buildHighlightsCarouselHtml(highlights, { title: details.name });
  const activityLines = (details.activities || [])
    .map((item) => formatHighlightLine(item))
    .filter(Boolean);

  return `
    ${
      carousel
        ? `
    <section class="dest-panel__highlights-section">
      <h3 class="dest-panel__section-title">Top things to do &amp; see</h3>
      ${carousel}
    </section>`
        : ""
    }
    ${
      activityLines.length
        ? `
    <section class="dest-panel__activities">
      <h3 class="dest-panel__section-title">Things to do</h3>
      <ul class="dest-panel__activity-list">
        ${activityLines.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>`
        : ""
    }
    ${buildNearbyCitiesHtml(details)}
    ${buildTimeOfYearHtml(details.country || "")}
    ${buildGoodToKnowHtml(details)}
  `;
}

function buildPoiStoryBody(details) {
  const highlights = details.highlights || [];
  const carousel = buildHighlightsCarouselHtml(highlights, { title: details.name });
  const activityLines = (details.activities || [])
    .map((item) => formatHighlightLine(item))
    .filter(Boolean);

  return `
    ${
      carousel
        ? `
    <section class="dest-panel__highlights-section">
      <h3 class="dest-panel__section-title">Why visit</h3>
      ${carousel}
    </section>`
        : ""
    }
    ${
      activityLines.length
        ? `
    <section class="dest-panel__activities">
      <h3 class="dest-panel__section-title">Things to do nearby</h3>
      <ul class="dest-panel__activity-list">
        ${activityLines.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </section>`
        : ""
    }
    ${buildTimeOfYearHtml(details.country || "")}
    ${buildGoodToKnowHtml(details)}
  `;
}

function buildPlaceStoryBody(details) {
  if (details.kind === "park") {
    return buildParkStoryBody(details);
  }
  if (details.kind === "poi") {
    return buildPoiStoryBody(details);
  }
  if (details.tier === "major" || details.isMajorCard) {
    return buildMajorPlaceStoryBody(details);
  }
  return `
    ${
      details.activities?.length
        ? `
    <section class="dest-panel__activities">
      <h3 class="dest-panel__section-title">Highlights</h3>
      <ul class="dest-panel__activity-list">
        ${details.activities
          .map((item) => formatHighlightLine(item))
          .filter(Boolean)
          .map((item) => `<li>${escapeHtml(item)}</li>`)
          .join("")}
      </ul>
    </section>`
        : ""
    }
    ${buildGoodToKnowHtml(details)}
  `;
}

function bindNearbyCityButtons(root) {
  root.querySelectorAll("[data-nearby-city-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const name = button.dataset.nearbyCityName;
      const country = button.dataset.nearbyCountry || "";
      const id = button.dataset.nearbyCityId;
      let details = null;
      if (id) {
        try {
          details = await fetchCityById(id, { name, country });
        } catch {
          details = null;
        }
      }
      await openPlaceStory(name, { country, ...(details || {}) });
    });
  });
}

function bindGoodToKnowAccordion(root) {
  root.querySelectorAll(".dest-panel__know-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const expanded = button.getAttribute("aria-expanded") === "true";
      const panel = document.getElementById(button.getAttribute("aria-controls"));
      button.setAttribute("aria-expanded", String(!expanded));
      if (panel) {
        panel.hidden = expanded;
        panel.classList.toggle("is-open", !expanded);
      }
    });
  });
}

let activeMapPopup = null;
let activeCityCatalogId = null;
let activeHikeCatalogId = null;
let activeParkCatalogId = null;
let hikeStoryCloseTimer = null;
let hikeStoryCloseGeneration = 0;
let placeStoryCloseGeneration = 0;
let placeStoryOpenGeneration = 0;
let placeStoryCloseTimer = null;
let activePlacePhotos = [];

function photoSourceFromEntry(entry) {
  if (!entry || typeof entry === "string") {
    return "";
  }
  if (entry.source) {
    return entry.source;
  }
  const caption = entry.caption || "";
  if (caption.toLowerCase().includes("wikimedia")) {
    return "Wikimedia Commons";
  }
  return "";
}

function updatePlaceStoryCredit(index = 0) {
  const creditEl = document.getElementById("placeStoryCredit");
  if (!creditEl) {
    return;
  }

  const entries = activePlacePhotos;
  if (!entries.length) {
    creditEl.hidden = true;
    creditEl.textContent = "";
    return;
  }

  const safeIndex = Math.min(Math.max(0, index), entries.length - 1);
  const entry = entries[safeIndex];
  const url = typeof entry === "string" ? entry : entry.url || entry.src || "";
  const source = photoSourceFromEntry(entry);

  if (source && url) {
    creditEl.hidden = false;
    creditEl.textContent = `Photo ${safeIndex + 1} · via ${source}`;
  } else {
    creditEl.hidden = true;
    creditEl.textContent = "";
  }
}

function revealPlaceStoryShell(title, props = {}) {
  const sheet = document.getElementById("placeStory");
  const titleEl = document.getElementById("placeStoryTitle");
  const taglineEl = document.getElementById("placeStoryTagline");
  const descEl = document.getElementById("placeStoryDescription");
  const bodyEl = document.getElementById("placeStoryBody");
  const countryEl = document.getElementById("placeStoryCountryName");

  if (!sheet || !titleEl || !bodyEl) {
    return false;
  }

  placeStoryCloseGeneration += 1;
  if (placeStoryCloseTimer) {
    clearTimeout(placeStoryCloseTimer);
    placeStoryCloseTimer = null;
  }

  const country = props.country || "";
  titleEl.textContent = title;
  if (taglineEl) {
    taglineEl.textContent = props.tagline || "Loading…";
  }
  if (descEl) {
    descEl.textContent = "Loading destination details…";
  }
  if (countryEl) {
    countryEl.textContent = country;
  }

  sheet.hidden = false;
  sheet.classList.remove("is-closing", "dest-panel--major", "dest-panel--park", "dest-panel--poi");
  void sheet.offsetWidth;
  sheet.classList.add("is-open");
  setDetailOverlayClass("place-story-open", true);
  requestAnimationFrame(updateLayoutInsets);
  return true;
}

async function openPlaceStory(title, props = {}) {
  const openId = ++placeStoryOpenGeneration;
  // Default: a place story opened from the map (marker, popup, stops list,
  // search, etc.) should NOT reopen the journey builder when it closes.
  // `focusBuilderStop` re-sets this flag *after* awaiting openPlaceStory.
  builderState.reopenAfterStory = false;
  closeHikeStory();
  map.closePopup();

  if (!revealPlaceStoryShell(title, props)) {
    return;
  }

  const sheet = document.getElementById("placeStory");
  const carouselHost = document.getElementById("placeStoryCarousel");
  const titleEl = document.getElementById("placeStoryTitle");
  const taglineEl = document.getElementById("placeStoryTagline");
  const descEl = document.getElementById("placeStoryDescription");
  const statsEl = document.getElementById("placeStoryStats");
  const bodyEl = document.getElementById("placeStoryBody");
  const flagEl = document.getElementById("placeStoryFlag");
  const countryEl = document.getElementById("placeStoryCountryName");

  let details = getPlaceDetail(title);
  const cityId = props.id || details.id;
  if (props.kind === "park" || details.kind === "park") {
    try {
      const fromDb = await fetchParkById(cityId || props.id);
      if (fromDb) {
        details = fromDb;
      }
    } catch {
      /* keep fallback */
    }
  } else if (props.kind === "poi" || details.kind === "poi") {
    try {
      const fromDb = await fetchPoiById(cityId || props.id);
      if (fromDb) {
        details = fromDb;
      }
    } catch {
      /* keep fallback */
    }
  } else if (cityCatalog && cityId) {
    try {
      const fromDb = await fetchCityById(cityId, { name: title, country: props.country || details.country, tier: props.tier || details.tier });
      if (fromDb) {
        details = fromDb;
      }
    } catch {
      /* keep cached detail */
    }
  } else if (!placeDetails[title] && cityCatalog) {
    const fromDb = await lookupCityByName(title, props.country || details.country || "");
    if (fromDb) {
      details = fromDb;
    }
  } else if (cityCatalog && !details.category) {
    try {
      const fromDb = await lookupCityByName(title, props.country || details.country || "");
      if (fromDb) {
        details = {
          ...details,
          category: details.category || fromDb.category,
          locale: details.locale || fromDb.locale,
          pop: details.pop ?? fromDb.pop,
          tier: details.tier || fromDb.tier,
          cc: details.cc || fromDb.cc,
          id: details.id || fromDb.id
        };
      }
    } catch {
      /* keep cached detail */
    }
  }

  if (openId !== placeStoryOpenGeneration || !sheet?.classList.contains("is-open")) {
    return;
  }

  const country = details.country || props.country || "";
  const dedupedPhotos = dedupePhotoEntries(normalizePhotoEntries(details.photos));
  const usedFingerprints = new Set(dedupedPhotos.map((p) => photoFingerprint(p.url)));
  const filteredHighlights = (details.highlights || []).filter((h) => {
    if (!h?.url) return false;
    const key = photoFingerprint(h.url);
    if (!key) return false;
    if (usedFingerprints.has(key)) return false;
    usedFingerprints.add(key);
    return true;
  });
  details = { ...details, photos: dedupedPhotos, highlights: filteredHighlights };
  activePlacePhotos = dedupedPhotos;

  titleEl.textContent = title;
  taglineEl.textContent = placeTagline(details);
  descEl.textContent = completeReadablePhrase(details.general || "", 2000);
  statsEl.innerHTML = buildPlaceStatsHtml(details, props);
  const isPark = details.kind === "park";
  const isPoi = details.kind === "poi";
  const isMajor = !isPark && !isPoi && (details.tier === "major" || details.isMajorCard);
  sheet.classList.toggle("dest-panel--park", isPark);
  sheet.classList.toggle("dest-panel--poi", isPoi);
  sheet.classList.toggle("dest-panel--major", isMajor);

  bodyEl.innerHTML = buildPlaceStoryBody(details);
  bindGoodToKnowAccordion(bodyEl);
  bindNearbyCityButtons(bodyEl);
  initHighlightsCarousels(bodyEl);

  if (countryEl) {
    countryEl.textContent = country;
  }

  if (flagEl) {
    const flagUrl = countryFlagUrl(country);
    if (flagUrl) {
      flagEl.hidden = false;
      flagEl.src = flagUrl;
      flagEl.alt = `Flag of ${country}`;
    } else {
      flagEl.hidden = true;
      flagEl.removeAttribute("src");
    }
  }

  if (carouselHost) {
    if (dedupedPhotos.length) {
      carouselHost.innerHTML = buildMediaCarouselHtml(dedupedPhotos, { variant: "dest", title });
      carouselHost.toggleAttribute("aria-hidden", false);
      initMediaCarousels(sheet);
    } else {
      const placeKind = isPark ? "park" : isPoi ? "poi" : "city";
      carouselHost.innerHTML = buildEmojiHeroHtml({
        emoji: emojiForPlace(title, placeKind),
        title,
        subtitle: country,
        variant: "dest"
      });
      carouselHost.toggleAttribute("aria-hidden", false);
    }
  }

  updatePlaceStoryCredit(0);

  if (openId !== placeStoryOpenGeneration) {
    return;
  }

  if (isPoi && (details.id || props.id)) {
    activePoiCatalogId = details.id || props.id;
    syncActivePoiMarkerStyles();
  } else if (isPark && (details.id || props.id)) {
    activeParkCatalogId = details.id || props.id;
    syncActiveParkMarkerStyles();
  }
  const favKind = isPark ? "park" : isPoi ? "poi" : "city";
  bindFavoriteButton(
    "placeStoryFavorite",
    favoriteEntryFromDetails(details, { ...props, kind: favKind })
  );
  setDetailOverlayClass("place-story-open", true);
  sheet.querySelector(".dest-panel__close")?.focus();
  requestAnimationFrame(updateLayoutInsets);
  requestAnimationFrame(syncMapPopupStacking);
}

function closePlaceStory() {
  const sheet = document.getElementById("placeStory");
  const closeGeneration = ++placeStoryCloseGeneration;
  placeStoryOpenGeneration += 1;

  if (placeStoryCloseTimer) {
    clearTimeout(placeStoryCloseTimer);
    placeStoryCloseTimer = null;
  }

  if (!sheet?.classList.contains("is-open")) {
    setDetailOverlayClass("place-story-open", false);
    restoreHudLayoutAfterDetailOverlay();
    return;
  }

  sheet.classList.remove("dest-panel--major", "dest-panel--park", "dest-panel--poi");
  activePoiCatalogId = null;
  syncActivePoiMarkerStyles();
  if (activeParkCatalogId) {
    activeParkCatalogId = null;
    syncActiveParkMarkerStyles();
    scheduleParkCatalogRefresh();
  }
  sheet.classList.add("is-closing");
  sheet.classList.remove("is-open");
  setDetailOverlayClass("place-story-open", false);

  const panel = sheet.querySelector(".dest-panel__card");
  const finish = () => {
    if (closeGeneration !== placeStoryCloseGeneration) {
      return;
    }
    sheet.hidden = true;
    sheet.classList.remove("is-closing");
    restoreHudLayoutAfterDetailOverlay();
  };

  if (panel) {
    panel.addEventListener("transitionend", finish, { once: true });
    placeStoryCloseTimer = window.setTimeout(finish, 480);
  } else {
    finish();
  }
  reopenBuilderIfPending();
}

function setupPlaceStory() {
  const sheet = document.getElementById("placeStory");
  if (!sheet) {
    return;
  }

  sheet.addEventListener("click", (event) => {
    if (event.target.closest("[data-place-story-close]")) {
      closePlaceStory();
    }
  });

  sheet.addEventListener("carouselchange", (event) => {
    if (!event.target.closest("#placeStoryCarousel [data-media-carousel]")) {
      return;
    }
    updatePlaceStoryCredit(event.detail?.index ?? 0);
  });

}

function setupDetailOverlayEscape() {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }

    const hikeSheet = document.getElementById("hikeStory");
    if (hikeSheet?.classList.contains("is-open") && !hikeSheet.hidden) {
      closeHikeStory();
      return;
    }

    const placeSheet = document.getElementById("placeStory");
    if (placeSheet?.classList.contains("is-open")) {
      closePlaceStory();
    }
  });
}

function refreshMapPopupLayout() {
  if (!activeMapPopup) {
    return;
  }

  activeMapPopup.options.maxWidth = 320;
  activeMapPopup.options.minWidth = 268;
  activeMapPopup.update();
}

function isMapPopupOpen() {
  const popup = map._popup;
  return Boolean(popup && typeof popup.isOpen === "function" && popup.isOpen());
}

/** Lift map popups above the fixed story panel (panel is outside #map stacking context). */
function syncMapPopupStacking() {
  const raise = isMapPopupOpen() && !panelCollapsed;
  document.body.classList.toggle("map-popup-raised", raise);
}

// Touch devices need bigger tap targets, but bumping marker radius too much
// makes neighbouring cities/parks/POIs merge visually in dense regions. A small
// +2 / +3px bump on coarse pointers strikes a balance: still respects neighbours
// because the relative spacing pattern is preserved, but each dot is much
// easier to land a fingertip on.
const TOUCH_HIT_BUMP = (() => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return 0;
  try {
    return window.matchMedia("(pointer: coarse)").matches ? 3 : 0;
  } catch {
    return 0;
  }
})();

function cityCatalogRadius(tier) {
  if (tier === "major") {
    return 7 + TOUCH_HIT_BUMP;
  }
  if (tier === "regional") {
    return 5 + TOUCH_HIT_BUMP;
  }
  return 4 + TOUCH_HIT_BUMP;
}

/** Cities with enriched copy / photos get an interactive deep-dive card; others are map dots only. */
function cityHasDeepDiveStory(props) {
  if (!props) {
    return false;
  }
  if (props.enriched === 1 || props.enriched === true) {
    return true;
  }
  if (props.enriched === 0 || props.enriched === false) {
    return false;
  }
  const text = `${props.general || ""} ${props.tagline || ""}`;
  if (/future deep-dive/i.test(text)) {
    return false;
  }
  return props.source === "trip";
}

/** Darker fill = capitals and major metros; lighter = regional / town / village.
 *  Tier (and category) drives the base lightness so a sleepy regional town
 *  never gets the same dark dot as a national capital, regardless of how
 *  large its population is relative to its country total. */
function cityCatalogFillColor(pop, cc, { hasStory = true, tier, category } = {}) {
  if (!hasStory) {
    return "hsl(215, 14%, 74%)";
  }

  const cat = (category || "").toLowerCase();
  const tierKey = (tier || "").toLowerCase();

  // Per-tier base lightness band. Lower = darker.
  // Tightened ranges so even small villages stay readable against the basemap.
  let baseLight;
  let lightSpan;
  if (cat === "capital" || tierKey === "major") {
    baseLight = 20;
    lightSpan = 8;
  } else if (cat === "metropolis") {
    baseLight = 28;
    lightSpan = 8;
  } else if (tierKey === "regional" || cat === "city") {
    baseLight = 40;
    lightSpan = 8;
  } else {
    baseLight = 52;
    lightSpan = 6;
  }

  const popNum = Number(pop) || 0;
  const stats = cityCountryPopStats?.byCc?.[cc];
  const countryTotal = Number(stats?.countryPopulation) || 0;

  let weight = 0.5;
  if (popNum && countryTotal) {
    const share = popNum / countryTotal;
    const capShare = 0.045;
    weight = Math.min(1, share / capShare);
    weight = Math.pow(weight, 0.62);
  }
  const lightness = Math.round(baseLight + (1 - weight) * lightSpan);
  return `hsl(215, 38%, ${lightness}%)`;
}

function cityCatalogMarkerStyle(props) {
  const hasStory = cityHasDeepDiveStory(props);
  const baseRadius = cityCatalogRadius(props.tier);

  return {
    pane: "citiesCatalog",
    radius: hasStory ? baseRadius : Math.max(3, baseRadius - 1),
    color: hasStory ? "#ffffff" : "rgba(255, 255, 255, 0.7)",
    weight: hasStory ? 1.5 : 1,
    fillColor: cityCatalogFillColor(props.pop, props.cc, {
      hasStory,
      tier: props.tier,
      category: props.category
    }),
    fillOpacity: hasStory ? 0.94 : 0.5,
    opacity: hasStory ? 1 : 0.65,
    interactive: hasStory,
    bubblingMouseEvents: !hasStory,
    className: hasStory
      ? "city-catalog-marker city-catalog-marker--story"
      : "city-catalog-marker city-catalog-marker--passive"
  };
}

function cityCatalogPopupHtml(props, details) {
  const cityId = props.id;
  const resolved = details || getCityDetail(cityCatalog, cityId, props);
  const title = resolved.name || props.name || "City";
  const countryLabel = resolved.country || props.country || "";
  const photos = normalizePhotoEntries(resolved.photos ?? props.photos);
  const photoCount = photos.length;
  const flagUrl = countryFlagUrl(countryLabel);
  const heroImg = buildPopupHeroImageTag(photos[0], title);

  return `
    <div class="marker-popup marker-popup-rich dest-popup-card dest-popup-card--catalog" data-place-name="${escapeHtml(title)}">
      <div class="dest-popup-card__hero${heroImg ? " dest-popup-card__hero--has-photo" : ""}">
        ${heroImg}
        <div class="dest-popup-card__hero-overlay">
          <div class="dest-popup-card__hero-gradient"></div>
          ${flagUrl ? `<img class="dest-popup-card__flag" src="${escapeAttr(flagUrl)}" alt="" width="14" height="14" loading="lazy" referrerpolicy="no-referrer" />` : ""}
          <h4 class="dest-popup-card__title">${escapeHtml(title)}</h4>
          <p class="dest-popup-card__tagline">${escapeHtml(placeTagline(resolved))}</p>
        </div>
      </div>
      <div class="dest-popup-card__body">
        ${countryLabel ? `<span class="dest-popup-card__country">${escapeHtml(countryLabel)}</span>` : ""}
        <span class="dest-popup-card__day">${escapeHtml(
          cityCategoryLabel(
            resolved.category || props.category,
            resolved.locale || props.locale
          )
        )}</span>
        <button type="button" class="popup-story-btn" data-place-story data-place-title="${escapeHtml(title)}">
          View city${photoCount > 0 ? ` · ${photoCount} photos` : ""}
        </button>
      </div>
    </div>
  `;
}

function isCityCatalogMarker(marker) {
  return Boolean(marker?._cityProps?.id);
}

/** Builds the small "preview" popup HTML for hike / park / POI markers — modeled
 * after `cityCatalogPopupHtml` but kind-aware so a single click handler can
 * route to the right `openXFromMarker` function via `data-marker-action`. */
function buildCatalogPreviewPopupHtml(kind, props, details) {
  const resolved = details || props || {};
  const title = resolved.name || props?.name || "Place";
  const countryLabel = resolved.country || props?.country || "";
  const photos = normalizePhotoEntries(resolved.photos ?? props?.photos);
  const photoCount = photos.length;
  const flagUrl = countryFlagUrl(countryLabel);
  const heroImg = buildPopupHeroImageTag(photos[0], title);
  const id = String(props?.id ?? resolved?.id ?? "");

  let typeLabel = "";
  let actionLabel = "View details";
  if (kind === "hike") {
    const length = formatHikeLength(resolved.length_km);
    const difficulty = resolved.difficulty
      ? formatHikeDifficultyLabel(resolved.difficulty).label
      : "";
    typeLabel = [length, difficulty].filter(Boolean).join(" · ") || "Hiking trail";
    actionLabel = "View trail";
  } else if (kind === "park") {
    typeLabel =
      parkCategoryLabel(resolved.category || props?.category) || "National park";
    actionLabel = "View park";
  } else if (kind === "poi") {
    typeLabel =
      resolved.category_label ||
      poiCategoryLabel(resolved.category || props?.category) ||
      "Place of interest";
    actionLabel = "View point";
  }

  return `
    <div class="marker-popup marker-popup-rich dest-popup-card dest-popup-card--catalog" data-place-name="${escapeAttr(title)}">
      <div class="dest-popup-card__hero${heroImg ? " dest-popup-card__hero--has-photo" : ""}">
        ${heroImg}
        <div class="dest-popup-card__hero-overlay">
          <div class="dest-popup-card__hero-gradient"></div>
          ${flagUrl ? `<img class="dest-popup-card__flag" src="${escapeAttr(flagUrl)}" alt="" width="14" height="14" loading="lazy" referrerpolicy="no-referrer" />` : ""}
          <h4 class="dest-popup-card__title">${escapeHtml(title)}</h4>
          <p class="dest-popup-card__tagline">${escapeHtml(placeTagline(resolved))}</p>
        </div>
      </div>
      <div class="dest-popup-card__body">
        ${countryLabel ? `<span class="dest-popup-card__country">${escapeHtml(countryLabel)}</span>` : ""}
        ${typeLabel ? `<span class="dest-popup-card__day">${escapeHtml(typeLabel)}</span>` : ""}
        <button type="button" class="popup-story-btn" data-marker-action data-marker-kind="${escapeAttr(kind)}" data-marker-id="${escapeAttr(id)}">
          ${escapeHtml(actionLabel)}${photoCount > 0 ? ` · ${photoCount} photos` : ""}
        </button>
      </div>
    </div>
  `;
}

/** Set to true while transitioning from a hike preview popup into the full
 * hike story so the popupclose handler skips clearing the trail route — the
 * full story will repaint it immediately and the brief gap would otherwise
 * cause a visible flicker. */
let catalogPreviewTransitioning = false;

function catalogPreviewPopupOptions() {
  return {
    maxWidth: 320,
    minWidth: 260,
    autoPan: true,
    autoPanPaddingTopLeft: L.point(24, 24),
    autoPanPaddingBottomRight: L.point(24, 160),
    closeButton: true
  };
}

/** Mobile-first preview: opens a small Leaflet popup with the marker info and,
 * for hikes, simultaneously paints the route on the map so the user can
 * inspect the trail without committing to the full story sheet. */
async function showCatalogMarkerPreview(marker, kind) {
  if (!marker) return;
  const propsKey = `_${kind}Props`;
  const detailsKey = `_${kind}Details`;
  const props = marker[propsKey];
  if (!props?.id) return;

  let details = marker[detailsKey] || null;
  if (!details) {
    try {
      if (kind === "hike") {
        details = await fetchHikeById(props.id);
      } else if (kind === "park") {
        details = await fetchParkById(props.id);
      } else if (kind === "poi") {
        details = await fetchPoiById(props.id);
      }
      if (details) {
        marker[detailsKey] = details;
      }
    } catch (error) {
      console.warn(`${kind} preview fetch failed:`, error);
    }
  }

  const html = buildCatalogPreviewPopupHtml(kind, props, details || props);

  if (kind === "hike") {
    activeHikeCatalogId = props.id;
    syncActiveHikeMarkerStyles();
    try {
      await showActiveHikeRoute(details || props);
    } catch (error) {
      console.warn("Hike preview route render failed:", error);
    }
  } else if (kind === "park") {
    activeParkCatalogId = props.id;
    syncActiveParkMarkerStyles();
  } else if (kind === "poi") {
    activePoiCatalogId = props.id;
    syncActivePoiMarkerStyles();
  }

  const latlng =
    typeof marker.getLatLng === "function" ? marker.getLatLng() : null;
  if (!latlng) return;

  L.popup(catalogPreviewPopupOptions())
    .setLatLng(latlng)
    .setContent(html)
    .openOn(map);
}

let citySearchResults = [];
let citySearchActiveIndex = -1;
let citySearchFetchId = 0;
let citySearchDebounceTimer = null;

function closeCitySearchResults() {
  const list = document.getElementById("citySearchResults");
  const input = document.getElementById("citySearchInput");
  list?.setAttribute("hidden", "");
  input?.setAttribute("aria-expanded", "false");
  citySearchActiveIndex = -1;
  citySearchResults = [];
  setCitySearchLoading(false);
}

function setCitySearchLoading(loading) {
  const spinner = document.getElementById("citySearchSpinner");
  if (!spinner) return;
  spinner.hidden = !loading;
}

const CITY_SEARCH_SUGGESTIONS = [
  { label: "Rome", icon: "🏛" },
  { label: "Plitvice", icon: "🌳" },
  { label: "Tour du Mont Blanc", icon: "🥾" },
  { label: "Dubrovnik", icon: "🏰" },
  { label: "Gibraltar", icon: "⛰" },
  { label: "Kotor", icon: "⛵" }
];

function showCitySearchHint() {
  const list = document.getElementById("citySearchResults");
  const input = document.getElementById("citySearchInput");
  if (!list || !input) return;
  if (input.value.trim().length >= 2) return;
  // The empty-state suggestion drawer is a touch-friendly affordance; on
  // desktop the old "no results until you type" behaviour worked fine.
  if (!window.matchMedia("(pointer: coarse)").matches) return;

  citySearchResults = [];
  citySearchActiveIndex = -1;
  list.innerHTML = `
    <li role="presentation" class="city-search__hint">
      <span class="city-search__hint-title">Try searching</span>
      <div class="city-search__hint-chips">
        ${CITY_SEARCH_SUGGESTIONS.map(
          (s) =>
            `<button type="button" class="city-search__hint-chip" data-suggestion="${escapeAttr(s.label)}"><span aria-hidden="true">${s.icon}</span>${escapeHtml(s.label)}</button>`
        ).join("")}
      </div>
      <span class="city-search__hint-foot">Type 2+ characters to find cities, parks, trails, and landmarks.</span>
    </li>
  `;
  list.removeAttribute("hidden");
  input.setAttribute("aria-expanded", "true");
  requestAnimationFrame(updateLayoutInsets);
}

function updateCitySearchActiveOption() {
  const list = document.getElementById("citySearchResults");
  list?.querySelectorAll(".city-search__option").forEach((button, index) => {
    const active = index === citySearchActiveIndex;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    if (active) {
      button.scrollIntoView({ block: "nearest" });
    }
  });
}

function renderCitySearchResults(results) {
  const list = document.getElementById("citySearchResults");
  const input = document.getElementById("citySearchInput");
  if (!list || !input) {
    return;
  }

  citySearchResults = results;
  citySearchActiveIndex = results.length ? 0 : -1;

  if (!results.length) {
    list.innerHTML = `<li class="city-search__empty" role="presentation">No results found</li>`;
    list.removeAttribute("hidden");
    input.setAttribute("aria-expanded", "true");
    requestAnimationFrame(updateLayoutInsets);
    return;
  }

  list.innerHTML = results
    .map((item, index) => {
      const isCountry = item.type === "country";
      const flagUrl = countryFlagUrl(item.country || item.name);
      let meta = "";

      if (isCountry) {
        const countLabel = item.cityCount ? `${item.cityCount.toLocaleString()} cities` : "Country";
        meta = countLabel;
      } else if (item.type === "hike") {
        const len = formatHikeLength(item.length_km);
        meta = [item.country, len, item.tier].filter(Boolean).join(" · ");
      } else if (item.type === "park") {
        const typeLabel = item.category ? parkCategoryLabel(item.category) : "";
        const bio = item.biodiversity ? `Biodiversity ${item.biodiversity}/5` : "";
        meta = [item.country, typeLabel, bio].filter(Boolean).join(" · ");
      } else if (item.type === "poi") {
        meta = [item.country, poiCategoryLabel(item.category), item.tier].filter(Boolean).join(" · ");
      } else {
        const popLabel =
          item.pop >= 1_000_000
            ? `${(item.pop / 1_000_000).toFixed(1)}M`
            : item.pop >= 1000
              ? `${Math.round(item.pop / 1000)}k`
              : "";
        const typeLabel = item.category ? cityCategoryLabel(item.category, item.locale) : "";
        meta = [item.country, typeLabel, popLabel].filter(Boolean).join(" · ");
      }

      const cityHasGuide =
        item.type !== "country" &&
        item.type !== "hike" &&
        item.type !== "park" &&
        item.type !== "poi" &&
        cityHasDeepDiveStory(item);
      const cityMapOnly =
        item.type !== "country" &&
        item.type !== "hike" &&
        item.type !== "park" &&
        item.type !== "poi" &&
        !cityHasGuide;

      return `
        <li role="presentation">
          <button
            type="button"
            class="city-search__option${index === 0 ? " is-active" : ""}${cityMapOnly ? " city-search__option--map-only" : ""}"
            role="option"
            data-index="${index}"
            aria-selected="${index === 0}"
          >
            ${
              flagUrl
                ? `<img class="city-search__flag" src="${escapeAttr(flagUrl)}" alt="" width="16" height="16" loading="lazy" referrerpolicy="no-referrer" />`
                : `<span class="city-search__flag-ph" aria-hidden="true"></span>`
            }
            <span class="city-search__option-text">
              <span class="city-search__name">${escapeHtml(item.name)}</span>
              ${meta ? `<span class="city-search__meta">${escapeHtml(meta)}</span>` : ""}
            </span>
            ${isCountry ? `<span class="city-search__kind">Country</span>` : ""}
            ${item.type === "hike" ? `<span class="city-search__kind city-search__kind--trail">Trail</span>` : ""}
            ${item.type === "park" ? `<span class="city-search__kind city-search__kind--park">National park</span>` : ""}
            ${item.type === "poi" ? `<span class="city-search__kind city-search__kind--poi">Landmark</span>` : ""}
            ${cityHasGuide ? `<span class="city-search__kind city-search__kind--guide">City guide</span>` : ""}
            ${cityMapOnly ? `<span class="city-search__kind city-search__kind--map">Map only</span>` : ""}
          </button>
        </li>
      `;
    })
    .join("");

  list.removeAttribute("hidden");
  input.setAttribute("aria-expanded", "true");
  requestAnimationFrame(updateLayoutInsets);
}

function scheduleCitySearch(query) {
  clearTimeout(citySearchDebounceTimer);
  const trimmed = query.trim();
  const clearBtn = document.getElementById("citySearchClear");
  const input = document.getElementById("citySearchInput");

  if (clearBtn) {
    clearBtn.hidden = !trimmed.length;
  }

  if (trimmed.length < 2) {
    setCitySearchLoading(false);
    if (input && document.activeElement === input) {
      showCitySearchHint();
    } else {
      closeCitySearchResults();
    }
    return;
  }

  setCitySearchLoading(true);
  citySearchDebounceTimer = window.setTimeout(async () => {
    const fetchId = ++citySearchFetchId;
    const regionId = cityCatalog?.id || "europe";

    try {
      const hikeRegionId = hikeCatalog?.id || "europe";
      const parkRegionId = parkCatalog?.id || "europe";
      const poiRegionId = poiCatalog?.id || "europe";
      const [placeResults, parkHits, hikeHits, poiHits] = await Promise.all([
        searchPlaces(trimmed, {
          regionId,
          countries: mapSearchCountries,
          cityLimit: 8,
          countryLimit: 4
        }),
        searchParks(trimmed, { regionId: parkRegionId, limit: 8 }).catch(() => []),
        searchHikes(trimmed, { regionId: hikeRegionId, limit: 10 }).catch(() => []),
        searchPois(trimmed, { regionId: poiRegionId, limit: 8 }).catch(() => [])
      ]);
      if (fetchId !== citySearchFetchId) {
        return;
      }

      const input = document.getElementById("citySearchInput");
      if (input?.value.trim() !== trimmed) {
        return;
      }

      const parkRows = (parkHits || []).map((p) => ({
        type: "park",
        kind: "park",
        id: p.id,
        name: p.name,
        country: p.country || "",
        lat: p.lat,
        lng: p.lng,
        category: p.category,
        tagline: p.tagline,
        tier: p.tier,
        biodiversity: p.biodiversity
      }));

      const hikeRows = (hikeHits || []).map((h) => ({
        type: "hike",
        id: h.id,
        name: h.name,
        country: h.country || "",
        lat: h.lat,
        lng: h.lng,
        length_km: h.length_km,
        tagline: h.tagline,
        tier: h.tier
      }));

      const poiRows = (poiHits || []).map((p) => ({
        type: "poi",
        kind: "poi",
        id: p.id,
        name: p.name,
        country: p.country || "",
        lat: p.lat,
        lng: p.lng,
        category: p.category,
        tagline: p.tagline,
        tier: p.tier,
        popularity: p.popularity
      }));

      renderCitySearchResults([...placeResults, ...parkRows, ...hikeRows, ...poiRows]);
    } catch (error) {
      console.warn("Search failed:", error);
    } finally {
      if (fetchId === citySearchFetchId) {
        setCitySearchLoading(false);
      }
    }
  }, 220);
}

async function goToCountryFromSearch(country) {
  if (!country) {
    return;
  }

  closeCitySearchResults();
  const input = document.getElementById("citySearchInput");
  if (input) {
    input.value = country.name;
    const clearBtn = document.getElementById("citySearchClear");
    if (clearBtn) {
      clearBtn.hidden = false;
    }
  }

  dismissWelcomeOverlay();

  if (country.cc) {
    void openCountryDossier({ cc: country.cc, country: country.name, bounds: country.bounds });
    return;
  }

  if (!country.bounds) {
    return;
  }

  setActiveView("map", { silent: true });
  if (!state.exploreCities) {
    setExploreCities(true);
  }

  const { west, south, east, north } = country.bounds;
  map.fitBounds(
    [
      [south, west],
      [north, east]
    ],
    { padding: [48, 48], maxZoom: 8 }
  );

  await new Promise((resolve) => {
    const onEnd = () => {
      map.off("moveend", onEnd);
      resolve();
    };
    map.on("moveend", onEnd);
    window.setTimeout(() => {
      map.off("moveend", onEnd);
      resolve();
    }, 1400);
  });

  syncCountryRegionsLayer();
  await refreshCityCatalogMarkers();
}

async function flyToCityOnMap(city) {
  if (city?.lat == null || city?.lng == null) {
    return;
  }

  closeCitySearchResults();
  const input = document.getElementById("citySearchInput");
  if (input) {
    input.value = city.name;
    const clearBtn = document.getElementById("citySearchClear");
    if (clearBtn) {
      clearBtn.hidden = false;
    }
  }

  dismissWelcomeOverlay();
  setActiveView("map", { silent: true });

  if (!state.exploreCities) {
    setExploreCities(true);
  }

  map.flyTo([city.lat, city.lng], 12, { duration: 0.85 });
  await refreshCityCatalogMarkers();
}

async function goToCityFromSearch(city) {
  if (city?.lat == null || city?.lng == null) {
    return;
  }

  if (!cityHasDeepDiveStory(city)) {
    await flyToCityOnMap(city);
    return;
  }

  closeCitySearchResults();
  const input = document.getElementById("citySearchInput");
  if (input) {
    input.value = city.name;
    const clearBtn = document.getElementById("citySearchClear");
    if (clearBtn) {
      clearBtn.hidden = false;
    }
  }

  dismissWelcomeOverlay();
  setActiveView("map", { silent: true });

  if (!state.exploreCities) {
    setExploreCities(true);
  }

  await new Promise((resolve) => {
    const onEnd = () => {
      map.off("moveend", onEnd);
      resolve();
    };
    map.on("moveend", onEnd);
    map.flyTo([city.lat, city.lng], 12, { duration: 0.85 });
    window.setTimeout(() => {
      map.off("moveend", onEnd);
      resolve();
    }, 1400);
  });

  await refreshCityCatalogMarkers();

  const marker = cityCatalogMarkersInView.get(city.id);
  const hasStory = cityHasDeepDiveStory(city) || marker?._cityHasStory;

  if (hasStory && marker) {
    marker.openPopup();
    return;
  }

  if (!hasStory) {
    return;
  }

  try {
    const details = await fetchCityById(city.id, city);
    if (!cityHasDeepDiveStory(details)) {
      return;
    }
    openPlaceStory(details.name || city.name, details);
  } catch {
    openPlaceStory(city.name, city);
  }
}

async function goToHikeFromSearch(hike) {
  if (!hike?.id || hike.lat == null || hike.lng == null) {
    return;
  }

  const fetchToken = ++hikeDetailFetchToken;
  activeHikeCatalogId = hike.id;
  syncActiveHikeMarkerStyles();

  closeCitySearchResults();
  const input = document.getElementById("citySearchInput");
  if (input) {
    input.value = hike.name;
    const clearBtn = document.getElementById("citySearchClear");
    if (clearBtn) {
      clearBtn.hidden = false;
    }
  }

  dismissWelcomeOverlay();
  setActiveView("map", { silent: true });

  if (!state.exploreHikes) {
    setExploreHikes(true, { keepDetailOpen: true });
  }

  await new Promise((resolve) => {
    const onEnd = () => {
      map.off("moveend", onEnd);
      resolve();
    };
    map.on("moveend", onEnd);
    map.flyTo([hike.lat, hike.lng], 11, { duration: 0.85 });
    window.setTimeout(() => {
      map.off("moveend", onEnd);
      resolve();
    }, 1400);
  });

  await refreshHikeCatalogMarkers();

  try {
    const details = await fetchHikeById(hike.id);
    if (fetchToken !== hikeDetailFetchToken) {
      abandonStaleHikeOpen(fetchToken, hike.id);
      return;
    }
    await showActiveHikeRoute(details);
    openHikeStory(details, hike);
  } catch (error) {
    if (fetchToken !== hikeDetailFetchToken) {
      abandonStaleHikeOpen(fetchToken, hike.id);
      return;
    }
    console.warn("Hike search open failed:", error);
    await showActiveHikeRoute(hike);
    openHikeStory(hike, hike);
  }
}

async function goToParkFromSearch(park) {
  if (!park?.id || park.lat == null || park.lng == null) {
    return;
  }

  closeCitySearchResults();
  const input = document.getElementById("citySearchInput");
  if (input) {
    input.value = park.name;
    const clearBtn = document.getElementById("citySearchClear");
    if (clearBtn) {
      clearBtn.hidden = false;
    }
  }

  dismissWelcomeOverlay();
  setActiveView("map", { silent: true });
  closeHikeStory();

  if (!state.exploreParks) {
    setExploreParks(true, { keepDetailOpen: true });
  }

  await new Promise((resolve) => {
    const onEnd = () => {
      map.off("moveend", onEnd);
      resolve();
    };
    map.on("moveend", onEnd);
    map.flyTo([park.lat, park.lng], 10, { duration: 0.85 });
    window.setTimeout(() => {
      map.off("moveend", onEnd);
      resolve();
    }, 1400);
  });

  await refreshParkCatalogMarkers();

  try {
    const details = await fetchParkById(park.id);
    await openPlaceStory(details.name || park.name, details);
  } catch (error) {
    console.warn("Park search open failed:", error);
    await openPlaceStory(park.name, { kind: "park", ...park });
  }
}

function setupCitySearch() {
  const input = document.getElementById("citySearchInput");
  const list = document.getElementById("citySearchResults");
  const clearBtn = document.getElementById("citySearchClear");
  const iconBtn = document.getElementById("citySearchIconButton");
  const root = document.getElementById("citySearch");

  if (!input || !list) {
    return;
  }

  input.addEventListener("input", () => {
    scheduleCitySearch(input.value);
  });

  input.addEventListener("focus", () => {
    if (citySearchResults.length) {
      list.removeAttribute("hidden");
      input.setAttribute("aria-expanded", "true");
    } else if (input.value.trim().length < 2) {
      showCitySearchHint();
    }
  });

  // The icon is now a <label for="citySearchInput">, which natively focuses
  // the input on tap (including raising the iOS keyboard). We just augment it
  // with a hint when the field is empty.
  iconBtn?.addEventListener("click", () => {
    if (input.value.trim().length < 2) {
      showCitySearchHint();
    }
  });

  // Make the entire pill background a tap target that focuses the input. The
  // individual children (icon <label>, the input itself, the clear button)
  // already focus correctly on their own — this only kicks in when the user
  // taps the padding around them. The clear button already calls
  // stopPropagation in its own click handler, so this never steals an X tap.
  const field = root?.querySelector(".city-search__field");
  field?.addEventListener("click", (event) => {
    const target = event.target;
    if (
      target === input ||
      target.closest?.(
        ".city-search__clear, .city-search__icon-button, .city-search__input"
      )
    ) {
      return;
    }
    input.focus();
  });

  // Prevent the clear button from stealing focus from the input on touch.
  // Without this, tapping ✕ blurs the input and the OS may also re-dispatch
  // a synthetic click to whatever lands under the finger after the DOM
  // changes (e.g. an empty-state suggestion chip), which is jarring.
  clearBtn?.addEventListener("pointerdown", (event) => {
    event.preventDefault();
  });
  clearBtn?.addEventListener("mousedown", (event) => {
    event.preventDefault();
  });
  clearBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    input.value = "";
    clearBtn.hidden = true;
    closeCitySearchResults();
    input.focus();
    // Defer the hint render so the synthetic click from this touch can't
    // accidentally land on a freshly rendered suggestion chip.
    requestAnimationFrame(() => {
      if (document.activeElement === input && input.value.trim().length < 2) {
        showCitySearchHint();
      }
    });
  });

  list.addEventListener("click", (event) => {
    const suggestion = event.target.closest("[data-suggestion]");
    if (suggestion) {
      input.value = suggestion.dataset.suggestion;
      input.focus();
      scheduleCitySearch(input.value);
      return;
    }

    const option = event.target.closest(".city-search__option");
    if (!option) {
      return;
    }

    const item = citySearchResults[Number(option.dataset.index)];
    if (item?.type === "country") {
      void goToCountryFromSearch(item);
    } else if (item?.type === "hike") {
      void goToHikeFromSearch(item);
    } else if (item?.type === "park") {
      void goToParkFromSearch(item);
    } else if (item?.type === "poi") {
      void goToPoiFromSearch(item);
    } else if (item) {
      if (cityHasDeepDiveStory(item)) {
        void goToCityFromSearch(item);
      } else {
        void flyToCityOnMap(item);
      }
    }
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeCitySearchResults();
      input.blur();
      return;
    }

    if (!citySearchResults.length || !list.querySelector(".city-search__option")) {
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      citySearchActiveIndex = Math.min(citySearchActiveIndex + 1, citySearchResults.length - 1);
      updateCitySearchActiveOption();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      citySearchActiveIndex = Math.max(citySearchActiveIndex - 1, 0);
      updateCitySearchActiveOption();
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = citySearchResults[citySearchActiveIndex];
      if (item?.type === "country") {
        void goToCountryFromSearch(item);
      } else if (item?.type === "hike") {
        void goToHikeFromSearch(item);
      } else if (item?.type === "park") {
        void goToParkFromSearch(item);
      } else if (item?.type === "poi") {
        void goToPoiFromSearch(item);
      } else if (item) {
        if (cityHasDeepDiveStory(item)) {
          void goToCityFromSearch(item);
        } else {
          void flyToCityOnMap(item);
        }
      }
    }
  });

  document.addEventListener("click", (event) => {
    if (!root?.contains(event.target)) {
      closeCitySearchResults();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    const target = event.target;
    const isEditable =
      target instanceof HTMLElement &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable);
    const meta = event.metaKey || event.ctrlKey;

    if (meta && event.key.toLowerCase() === "k") {
      event.preventDefault();
      input.focus();
      input.select();
      if (input.value.trim().length < 2) showCitySearchHint();
      return;
    }

    if (event.key === "/" && !isEditable && !meta && !event.altKey) {
      event.preventDefault();
      input.focus();
      if (input.value.trim().length < 2) showCitySearchHint();
    }
  });
}

async function ensureCityCatalogPopupContent(marker) {
  const props = marker._cityProps;
  if (!props) {
    return;
  }

  if (marker._cityDetailsPromise) {
    await marker._cityDetailsPromise;
    return;
  }

  marker._cityDetailsPromise = fetchCityById(props.id, props)
    .then((details) => {
      marker._cityDetails = details;
      const html = cityCatalogPopupHtml(props, details);
      marker._cityPopupHtml = html;
      if (marker.isPopupOpen()) {
        marker.setPopupContent(html);
        initMediaCarousels(marker.getPopup()?.getElement?.());
        refreshMapPopupLayout();
      }
      return details;
    })
    .catch((error) => {
      console.warn("City detail fetch failed:", error);
      marker._cityPopupHtml = cityCatalogPopupHtml(props, null);
      if (marker.isPopupOpen()) {
        marker.setPopupContent(marker._cityPopupHtml);
      }
    })
    .finally(() => {
      marker._cityDetailsPromise = null;
    });

  await marker._cityDetailsPromise;
}

function createCityCatalogMarker(props, lat, lng) {
  const hasStory = cityHasDeepDiveStory(props);
  const marker = L.circleMarker([lat, lng], cityCatalogMarkerStyle(props));

  marker._cityProps = props;
  marker._cityHasStory = hasStory;

  marker.on("mousedown touchstart", L.DomEvent.stopPropagation);

  if (!hasStory) {
    return marker;
  }

  marker.bindPopup('<div class="marker-popup">Loading city…</div>', {
    maxWidth: 320,
    minWidth: 260,
    autoPan: true,
    autoPanPaddingTopLeft: L.point(24, 24),
    autoPanPaddingBottomRight: L.point(24, 160)
  });
  marker.on("click", (event) => {
    L.DomEvent.stopPropagation(event);
    void ensureCityCatalogPopupContent(marker);
  });

  marker.on("popupopen", () => {
    activeCityCatalogId = props.id;
    if (marker._cityDetails) {
      marker._cityPopupHtml = cityCatalogPopupHtml(props, marker._cityDetails);
      marker.setPopupContent(marker._cityPopupHtml);
      initMediaCarousels(marker.getPopup()?.getElement?.());
      refreshMapPopupLayout();
      return;
    }
    if (marker._cityPopupHtml) {
      marker.setPopupContent(marker._cityPopupHtml);
      initMediaCarousels(marker.getPopup()?.getElement?.());
      refreshMapPopupLayout();
    }
    void ensureCityCatalogPopupContent(marker);
  });

  marker.on("popupclose", () => {
    if (activeCityCatalogId === props.id) {
      activeCityCatalogId = null;
    }
    scheduleCityCatalogRefresh();
  });

  return marker;
}

function replaceCityCatalogMarker(props, lat, lng) {
  const id = props.id;
  const existing = cityCatalogMarkersInView.get(id);
  if (existing) {
    cityCatalogLayer?.removeLayer(existing);
    cityCatalogMarkersInView.delete(id);
  }
  const marker = createCityCatalogMarker(props, lat, lng);
  cityCatalogMarkersInView.set(id, marker);
  cityCatalogLayer?.addLayer(marker);
  return marker;
}

async function refreshCityCatalogMarkers() {
  if (!state.exploreCities || !cityCatalogLayer || !cityCatalog) {
    return;
  }

  const bounds = map.getBounds();
  const zoom = map.getZoom();
  syncCountryRegionsLayer();

  const fetchId = ++cityCatalogFetchId;

  let geojson;
  try {
    geojson = await fetchCityFeatures(
      cityCatalog.id,
      {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth()
      },
      zoom
    );
  } catch (error) {
    console.warn("City features fetch failed:", error);
    return;
  }

  if (fetchId !== cityCatalogFetchId || !state.exploreCities) {
    return;
  }

  const visibleIds = new Set();
  const features = geojson?.features || [];

  features.forEach((feature) => {
    const props = feature.properties || {};
    const [lng, lat] = feature.geometry.coordinates;

    visibleIds.add(props.id);

    const existing = cityCatalogMarkersInView.get(props.id);
    const hadStory = existing ? cityHasDeepDiveStory(existing._cityProps) : null;
    const hasStory = cityHasDeepDiveStory(props);

    if (!existing) {
      replaceCityCatalogMarker(props, lat, lng);
    } else if (hadStory !== hasStory) {
      replaceCityCatalogMarker(props, lat, lng);
    } else {
      existing._cityProps = props;
      existing._cityHasStory = hasStory;
      existing.setStyle(cityCatalogMarkerStyle(props));
    }
  });

  cityCatalogMarkersInView.forEach((marker, id) => {
    if (visibleIds.has(id) || id === activeCityCatalogId) {
      return;
    }
    cityCatalogLayer.removeLayer(marker);
    cityCatalogMarkersInView.delete(id);
  });
}

function scheduleCityCatalogRefresh() {
  if (!state.exploreCities) {
    return;
  }
  if (activeCityCatalogId) {
    return;
  }
  clearTimeout(cityCatalogRefreshTimer);
  cityCatalogRefreshTimer = setTimeout(() => {
    refreshCityCatalogMarkers();
  }, 120);
}

function bindExploreCatalogMapEvents() {
  if (map._exploreCatalogEventsBound) {
    return;
  }
  map._exploreCatalogEventsBound = true;
  map.on("moveend zoomend", () => {
    syncCountryRegionsLayer();
    scheduleCityCatalogRefresh();
    scheduleParkCatalogRefresh();
    schedulePoiCatalogRefresh();
    scheduleHikeCatalogRefresh();
  });
}

function clearCityCatalogMarkers() {
  cityCatalogLayer?.clearLayers();
  cityCatalogMarkersInView.clear();
}

function buildCityCatalogLayer() {
  if (!cityCatalog) {
    return;
  }

  if (!cityCatalogLayer) {
    cityCatalogLayer = L.layerGroup();
  } else {
    clearCityCatalogMarkers();
  }

  bindExploreCatalogMapEvents();
  refreshCityCatalogMarkers();
}

function setExploreCities(enabled) {
  state.exploreCities = enabled;
  const anyExplore = enabled || state.exploreParks || state.exploreHikes || state.explorePoi;
  document.body.classList.toggle("explore-mode-on", anyExplore);
  layoutRoot?.classList.toggle("map-stage--explore", anyExplore);

  if (enabled) {
    if (!cityCatalogLayer && cityCatalog) {
      buildCityCatalogLayer();
    }
    if (cityCatalogLayer && !map.hasLayer(cityCatalogLayer)) {
      cityCatalogLayer.addTo(map);
    }
    if (!countryRegionsLayer) {
      void initCountryBorders();
    } else {
      syncCountryRegionsLayer();
    }
    refreshCityCatalogMarkers();
    mapEl?.classList.add("explore-cities-on");
  } else {
    if (cityCatalogLayer && map.hasLayer(cityCatalogLayer)) {
      map.removeLayer(cityCatalogLayer);
    }
    clearCityCatalogMarkers();
    map.closePopup();
    mapEl?.classList.remove("explore-cities-on");
    syncCountryRegionsLayer();
  }

  updateExploreCitiesUi();
  updateHudJourneyState();
}

function syncExploreHudButton() {
  const citiesOn = state.exploreCities === true;
  const parksOn = state.exploreParks === true;
  const hikesOn = state.exploreHikes === true;
  const poisOn = state.explorePoi === true;
  const active = citiesOn || parksOn || hikesOn || poisOn;

  if (exploreModeBtn) {
    exploreModeBtn.dataset.active = String(active);
    exploreModeBtn.setAttribute("aria-pressed", String(active));
    exploreModeBtn.classList.toggle("is-active", active);
  }

  const exploreHint = document.getElementById("exploreModeHint");
  if (exploreHint) {
    if (!active) {
      exploreHint.textContent = "Cities · parks · trails · landmarks";
    } else {
      const parts = [];
      if (citiesOn) {
        parts.push("cities");
      }
      if (parksOn) {
        parts.push("parks");
      }
      if (hikesOn) {
        parts.push("trails");
      }
      if (poisOn) {
        parts.push("landmarks");
      }
      exploreHint.textContent = `${parts.join(" · ")} on — tap a marker`;
    }
  }
}

function updateExploreCitiesUi() {
  const active = state.exploreCities === true;
  const chip = document.getElementById("exploreCitiesChip");
  if (chip) {
    chip.dataset.active = String(active);
    chip.setAttribute("aria-pressed", String(active));
  }
  syncExploreHudButton();
}

function renderExploreCitiesToggle() {
  const container = document.getElementById("exploreCitiesToggle");
  if (!container) {
    return;
  }

  const count = cityCatalog?.count || 0;
  const active = state.exploreCities === true;
  container.innerHTML = `
    <button
      type="button"
      id="exploreCitiesChip"
      class="layer-chip layer-chip--explore"
      data-active="${String(active)}"
      aria-pressed="${String(active)}"
      title="Show European city markers on the map"
    >Cities${count ? ` (${count.toLocaleString()})` : ""}</button>
  `;
  updateExploreCitiesUi();
}

function setupExploreCitiesToggle() {
  const row = document.getElementById("exploreLayersRow");
  if (!row || row.dataset.citiesBound === "true") {
    return;
  }
  row.dataset.citiesBound = "true";
  row.addEventListener("click", (event) => {
    if (event.target.closest("#exploreCitiesChip")) {
      setExploreCities(!state.exploreCities);
    }
  });
  renderExploreCitiesToggle();
}

async function initCityCatalog() {
  try {
    cityCatalog = await loadCityRegion("europe");
    renderExploreCitiesToggle();
    await initCountryBorders();
    try {
      cityCountryPopStats = await fetchCountryPopStats(cityCatalog.id);
      cityCatalogMarkersInView.forEach((marker) => {
        const props = marker._cityProps;
        if (props) {
          marker.setStyle(cityCatalogMarkerStyle(props));
        }
      });
    } catch (error) {
      console.warn("Country population stats not loaded:", error);
    }
    try {
      mapSearchCountries = await fetchCountries(cityCatalog.id);
    } catch (error) {
      console.warn("Country search list not loaded:", error);
    }
  } catch (error) {
    console.warn("City catalog not loaded:", error);
  }
}

function hikeCatalogRadius(tier) {
  if (tier === "major") {
    return 8 + TOUCH_HIT_BUMP;
  }
  if (tier === "regional") {
    return 6 + TOUCH_HIT_BUMP;
  }
  return 4 + TOUCH_HIT_BUMP;
}

function formatHikeLength(km) {
  if (km == null || Number.isNaN(Number(km))) {
    return "";
  }
  const value = Number(km);
  if (value >= 100) {
    return `${Math.round(value)} km`;
  }
  if (value >= 10) {
    return `${value.toFixed(0)} km`;
  }
  return `${value.toFixed(1)} km`;
}

function formatHikeDifficultyLabel(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (!value) {
    return { label: "Moderate", level: "moderate" };
  }

  const sacMap = {
    hiking: { label: "Easy hiking", level: "easy" },
    mountain_hiking: { label: "Mountain hiking", level: "moderate" },
    demanding_mountain_hiking: { label: "Demanding", level: "hard" },
    alpine_hiking: { label: "Alpine", level: "alpine" },
    difficult_alpine_hiking: { label: "Difficult alpine", level: "alpine" }
  };
  if (sacMap[value]) {
    return sacMap[value];
  }

  if (/easy|beginner|t1/i.test(value)) {
    return { label: "Easy", level: "easy" };
  }
  if (/moderate|intermediate|t2/i.test(value)) {
    return { label: "Moderate", level: "moderate" };
  }
  if (/hard|difficult|strenuous|t3|t4|t5|demanding/i.test(value)) {
    return { label: "Hard", level: "hard" };
  }
  if (/alpine|expert|extreme/i.test(value)) {
    return { label: "Alpine", level: "alpine" };
  }

  const label = value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, level: "moderate" };
}

function detailPanelReservePx() {
  const hikeSheet = document.getElementById("hikeStory");
  if (hikeSheet?.classList.contains("is-open")) {
    const hikeCard = hikeSheet.querySelector(".dest-panel__card");
    if (hikeCard) {
      return Math.round(hikeCard.getBoundingClientRect().width + 28);
    }
    return 448;
  }

  const placeSheet = document.getElementById("placeStory");
  if (placeSheet?.classList.contains("is-open")) {
    const placeCard = placeSheet.querySelector(".dest-panel__card");
    if (placeCard) {
      return Math.round(placeCard.getBoundingClientRect().width + 28);
    }
    return 448;
  }

  if (!panelCollapsed && itineraryPanel) {
    const panelWidth = Math.round(itineraryPanel.getBoundingClientRect().width);
    if (panelWidth > 80) {
      return panelWidth + 16;
    }
  }

  return 0;
}

function hikeFitBoundsOptions() {
  const base = 56;
  const maxZoom = 13;

  // Phone layout: the journey panel + bottom nav sit at the BOTTOM of the
  // screen and the slim HUD search bar at the top — they're not a right-edge
  // panel like desktop, so feeding their width into paddingBottomRight (as
  // `detailPanelReservePx` does) drives the effective fit area negative and
  // leaves the map zoomed to nonsense. Reserve the actual top/bottom strips
  // instead so the trail centres in the visible map slice.
  const isPhone =
    typeof window !== "undefined" &&
    window.matchMedia("(max-width: 640px)").matches;

  if (isPhone) {
    const topReserve =
      Math.max(
        56,
        document.querySelector(".map-hud")?.getBoundingClientRect().height || 0
      ) + 12;
    const navHeight =
      document.getElementById("mobileBottomNav")?.getBoundingClientRect()
        .height || 0;
    const panel = document.getElementById("itineraryPanel");
    const panelHeight =
      panel && !panel.hidden
        ? Math.min(160, panel.getBoundingClientRect().height || 110)
        : 0;
    const bottomReserve = navHeight + panelHeight + 16;

    return {
      paddingTopLeft: L.point(20, topReserve),
      paddingBottomRight: L.point(20, bottomReserve),
      maxZoom
    };
  }

  const reserve = detailPanelReservePx();
  if (reserve > 0) {
    return {
      paddingTopLeft: L.point(base, base),
      paddingBottomRight: L.point(base + reserve, base),
      maxZoom
    };
  }

  return { padding: L.point(base, base), maxZoom };
}

function refitActiveHikeRoute() {
  if (!activeHikeRouteLayer) {
    return;
  }

  const bounds = activeHikeRouteLayer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, hikeFitBoundsOptions());
  }
}

function syncActiveHikeMarkerStyles() {
  hikeCatalogMarkersInView.forEach((marker, id) => {
    const props = marker._hikeProps || {};
    const selected = id === activeHikeCatalogId;
    marker.setStyle({
      pane: "hikesCatalog",
      radius: hikeCatalogRadius(props.tier),
      color: "#ffffff",
      weight: selected ? 2.5 : 1.5,
      fillColor: selected ? "#9a3412" : "#c2410c",
      fillOpacity: selected ? 1 : 0.94,
      opacity: 1,
      className: selected ? "hike-catalog-marker is-selected" : "hike-catalog-marker"
    });
  });
}

function buildHikeStatsHtml(detail) {
  const items = [];
  const lengthLabel = formatHikeLength(detail.length_km);
  if (lengthLabel) {
    items.push({ icon: "📏", label: "Distance", value: lengthLabel });
  }
  if (detail.ascent_m) {
    items.push({ icon: "⬆", label: "Ascent", value: `${Math.round(detail.ascent_m)} m` });
  }
  const difficulty = formatHikeDifficultyLabel(detail.difficulty);
  items.push({ icon: "🥾", label: "Difficulty", value: difficulty.label });
  if (detail.network) {
    items.push({ icon: "🗺", label: "Network", value: String(detail.network).toUpperCase() });
  }
  if (detail.route_type) {
    items.push({
      icon: "〰",
      label: "Route type",
      value: String(detail.route_type).replace(/_/g, " ")
    });
  }
  if (detail.osm_id) {
    items.push({
      icon: "🔗",
      label: "OpenStreetMap",
      value: `relation ${detail.osm_id}`
    });
  }

  return items
    .map(
      (item) => `
      <dt class="dest-panel__stat-label"><span aria-hidden="true">${item.icon}</span> ${escapeHtml(item.label)}</dt>
      <dd class="dest-panel__stat-value">${escapeHtml(item.value)}</dd>
    `
    )
    .join("");
}

function buildHikeStartHtml(detail) {
  const start = detail?.start;
  const end = detail?.end;
  const instructions = (detail?.start_instructions || "").trim();
  if (!start && !instructions) {
    return "";
  }

  const lines = [];
  if (start) {
    if (start.name && end?.name && end.name.toLowerCase() !== start.name.toLowerCase()) {
      lines.push(
        `<div class="dest-panel__trail-start-where"><strong>Start:</strong> ${escapeHtml(start.name)} <span class="dest-panel__trail-start-sep">→</span> <strong>Finish:</strong> ${escapeHtml(end.name)}</div>`
      );
    } else if (start.name) {
      lines.push(
        `<div class="dest-panel__trail-start-where"><strong>Trailhead:</strong> ${escapeHtml(start.name)}</div>`
      );
    }
    const lat = Number(start.lat);
    const lng = Number(start.lng);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      const coordHtml = `${lat.toFixed(4)}°, ${lng.toFixed(4)}°`;
      const mapsHref = `https://www.google.com/maps?q=${lat.toFixed(5)},${lng.toFixed(5)}`;
      lines.push(
        `<div class="dest-panel__trail-start-coords">` +
          `<span class="dest-panel__trail-start-pin" aria-hidden="true">📍</span> ` +
          `<span class="dest-panel__trail-start-coord-text">${coordHtml}</span> ` +
          `<a class="dest-panel__trail-start-link" href="${escapeHtml(mapsHref)}" target="_blank" rel="noopener">Open in Maps</a>` +
          `</div>`
      );
    }
  }

  if (instructions) {
    lines.push(
      `<p class="dest-panel__trail-start-instructions">${escapeHtml(instructions)}</p>`
    );
  }

  return `
    <section class="dest-panel__know dest-panel__trail-start-card">
      <h3 class="dest-panel__section-title">Where to start</h3>
      ${lines.join("\n")}
    </section>
  `;
}

function buildHikeTipsHtml(detail) {
  const raw = Array.isArray(detail.tips) ? detail.tips.map((t) => String(t).trim()).filter(Boolean) : [];
  const defaults = [
    "Check a reliable mountain weather forecast the evening before; turn back if lightning or whiteout risk is forecast.",
    "Bring more water and calories than a city walk — filter or tablets if you plan to refill from streams.",
    "Battery dies cold and fast: offline map, whistle, and a compact headlamp belong in every pack.",
    "Closed gates, hunting seasons, and wildlife calving windows can restrict access — verify locally.",
    "Tell someone outside the group where you are going and when you expect to be off the trail.",
    "Cairns and unofficial paths erode fragile ground — stay on the signed line when one exists.",
  ];
  const seen = new Set(raw.map((t) => t.toLowerCase().slice(0, 52)));
  const merged = [...raw];
  for (const line of defaults) {
    if (merged.length >= 7) {
      break;
    }
    const key = line.toLowerCase().slice(0, 52);
    if (!seen.has(key)) {
      merged.push(line);
      seen.add(key);
    }
  }

  return `
    <section class="dest-panel__know dest-panel__trail-tips">
      <h3 class="dest-panel__section-title">Trail tips</h3>
      <ul class="dest-panel__activity-list dest-panel__trail-tips-list">
        ${merged.map((tip) => `<li>${escapeHtml(tip)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function isHikeStoryVisible() {
  const sheet = document.getElementById("hikeStory");
  return Boolean(sheet?.classList.contains("is-open") && !sheet.hidden);
}

function syncHikeStoryOverlayLayout() {
  setDetailOverlayClass("hike-story-open", isHikeStoryVisible());
  if (!isHikeStoryVisible()) {
    requestAnimationFrame(updateLayoutInsets);
  }
}

function openHikeStory(detail, props = {}) {
  // Default: a hike story opened from the map should NOT reopen the journey
  // builder on close. `focusBuilderStop` re-sets this flag after calling.
  builderState.reopenAfterStory = false;
  closePlaceStory();
  const sheet = document.getElementById("hikeStory");
  const titleEl = document.getElementById("hikeStoryTitle");
  const taglineEl = document.getElementById("hikeStoryTagline");
  const descEl = document.getElementById("hikeStoryDescription");
  const statsEl = document.getElementById("hikeStoryStats");
  const tipsEl = document.getElementById("hikeStoryTips");
  const creditEl = document.getElementById("hikeStoryCredit");
  const countryEl = document.getElementById("hikeStoryCountryName");

  const carouselHost = document.getElementById("hikeStoryCarousel");
  const pillEl = document.getElementById("hikeStoryDifficultyPill");

  if (!sheet || !titleEl || !descEl) {
    return;
  }

  const resolved = detail || props;
  const hikeId = resolved.id || props.id || null;
  const title = resolved.name || props.name || "Trail";
  const country = resolved.country || props.country || "";
  const difficulty = formatHikeDifficultyLabel(resolved.difficulty || props.difficulty);
  const summary = resolved.summary || resolved.tagline || props.tagline || "European hiking route from OpenStreetMap.";

  hikeStoryCloseGeneration += 1;
  if (hikeStoryCloseTimer) {
    clearTimeout(hikeStoryCloseTimer);
    hikeStoryCloseTimer = null;
  }

  if (hikeId) {
    activeHikeCatalogId = hikeId;
    syncActiveHikeMarkerStyles();
  }

  titleEl.textContent = title;
  taglineEl.textContent = resolved.tagline || formatHikeLength(resolved.length_km) || "Hiking trail";
  descEl.textContent = summary;

  if (carouselHost) {
    const photos = dedupePhotoEntries(normalizePhotoEntries(resolved.photos));
    if (photos.length) {
      carouselHost.innerHTML = buildMediaCarouselHtml(photos, { variant: "dest", title });
      carouselHost.toggleAttribute("aria-hidden", false);
      initMediaCarousels(sheet);
    } else {
      carouselHost.innerHTML = buildEmojiHeroHtml({
        emoji: emojiForPlace(title, "hike"),
        title,
        subtitle: country,
        variant: "dest"
      });
      carouselHost.toggleAttribute("aria-hidden", false);
    }
  }

  const startEl = document.getElementById("hikeStoryStart");
  if (startEl) {
    const startHtml = buildHikeStartHtml(resolved);
    if (startHtml) {
      startEl.innerHTML = startHtml;
      startEl.hidden = false;
    } else {
      startEl.innerHTML = "";
      startEl.hidden = true;
    }
  }
  if (statsEl) {
    statsEl.innerHTML = buildHikeStatsHtml(resolved);
  }
  if (tipsEl) {
    tipsEl.innerHTML = buildHikeTipsHtml(resolved);
  }
  if (countryEl) {
    countryEl.textContent = country || "Europe";
  }
  if (creditEl) {
    creditEl.textContent = `Route geometry: ${resolved.source || "OpenStreetMap"}. Always verify conditions locally.`;
  }
  if (pillEl) {
    pillEl.dataset.level = difficulty.level;
    pillEl.textContent = difficulty.label;
  }

  sheet.hidden = false;
  sheet.classList.remove("is-closing");
  void sheet.offsetWidth;
  sheet.classList.add("is-open");
  syncHikeStoryOverlayLayout();
  sheet.querySelector(".dest-panel__close")?.focus();
  bindFavoriteButton(
    "hikeStoryFavorite",
    favoriteEntryFromDetails(resolved, { ...props, kind: "hike" })
  );
  requestAnimationFrame(() => {
    updateLayoutInsets();
    refitActiveHikeRoute();
    requestAnimationFrame(refitActiveHikeRoute);
  });
}

function abandonStaleHikeOpen(fetchToken, hikeId) {
  if (fetchToken === hikeDetailFetchToken || isHikeStoryVisible()) {
    return;
  }
  if (hikeId && activeHikeCatalogId === hikeId) {
    activeHikeCatalogId = null;
    clearActiveHikeRoute();
    syncActiveHikeMarkerStyles();
    syncHikeStoryOverlayLayout();
  }
}

function closeHikeStory(options = {}) {
  // `keepRoute: true` leaves the trail polyline + endpoint pins painted on the
  // map after the panel slides away — used when the user explicitly dismisses
  // the panel (X / backdrop) so they can keep eyeing the route. Programmatic
  // closes (loading another marker, deselecting a journey, etc.) default to
  // clearing because a new selection is about to take over.
  const { keepRoute = false } = options;
  const sheet = document.getElementById("hikeStory");
  const wasOpen = Boolean(sheet?.classList.contains("is-open"));
  if (wasOpen) {
    hikeDetailFetchToken += 1;
  }
  const closeGeneration = ++hikeStoryCloseGeneration;

  if (hikeStoryCloseTimer) {
    clearTimeout(hikeStoryCloseTimer);
    hikeStoryCloseTimer = null;
  }

  const finishClose = () => {
    if (closeGeneration !== hikeStoryCloseGeneration) {
      return;
    }

    sheet.hidden = true;
    sheet.classList.remove("is-open", "is-closing");
    if (!keepRoute) {
      activeHikeCatalogId = null;
      clearActiveHikeRoute();
      syncActiveHikeMarkerStyles();
    }
    syncHikeStoryOverlayLayout();
    restoreHudLayoutAfterDetailOverlay();
  };

  if (!sheet?.classList.contains("is-open")) {
    if (sheet) {
      finishClose();
    } else if (!keepRoute) {
      activeHikeCatalogId = null;
      clearActiveHikeRoute();
      syncActiveHikeMarkerStyles();
      syncHikeStoryOverlayLayout();
      restoreHudLayoutAfterDetailOverlay();
    }
    return;
  }

  sheet.classList.add("is-closing");
  sheet.classList.remove("is-open");
  syncHikeStoryOverlayLayout();
  restoreHudLayoutAfterDetailOverlay();

  const panel = sheet.querySelector(".dest-panel__card");
  if (panel) {
    panel.addEventListener("transitionend", finishClose, { once: true });
    hikeStoryCloseTimer = window.setTimeout(finishClose, 480);
  } else {
    finishClose();
  }
  reopenBuilderIfPending();
}

function setupHikeStory() {
  const sheet = document.getElementById("hikeStory");
  if (!sheet || sheet.dataset.hikeStoryBound === "true") {
    return;
  }
  sheet.dataset.hikeStoryBound = "true";

  sheet.addEventListener("click", (event) => {
    if (event.target.closest("[data-hike-story-close]")) {
      closeHikeStory({ keepRoute: true });
    }
  });

}

async function openHikeFromMarker(marker) {
  const props = marker._hikeProps;
  if (!props?.id) {
    return;
  }

  if (marker._hikeOpening) {
    return;
  }

  if (activeHikeCatalogId === props.id && isHikeStoryVisible()) {
    return;
  }

  marker._hikeOpening = true;
  activeHikeCatalogId = props.id;
  syncActiveHikeMarkerStyles();
  map.closePopup();
  closePlaceStory();

  const fetchToken = ++hikeDetailFetchToken;

  try {
    let details = marker._hikeDetails;
    if (!details) {
      details = await fetchHikeById(props.id);
      marker._hikeDetails = details;
    }
    if (fetchToken !== hikeDetailFetchToken) {
      abandonStaleHikeOpen(fetchToken, props.id);
      return;
    }
    await showActiveHikeRoute(details);
    openHikeStory(details, props);
  } catch (error) {
    if (fetchToken !== hikeDetailFetchToken) {
      abandonStaleHikeOpen(fetchToken, props.id);
      return;
    }
    console.warn("Hike detail fetch failed:", error);
    await showActiveHikeRoute(props);
    openHikeStory(props, props);
  } finally {
    marker._hikeOpening = false;
  }
}

function clearActiveHikeRoute() {
  if (activeHikeRouteLayer && map.hasLayer(activeHikeRouteLayer)) {
    map.removeLayer(activeHikeRouteLayer);
  }
  if (activeHikeRouteGlowLayer && map.hasLayer(activeHikeRouteGlowLayer)) {
    map.removeLayer(activeHikeRouteGlowLayer);
  }
  if (activeHikeEndpointsLayer && map.hasLayer(activeHikeEndpointsLayer)) {
    map.removeLayer(activeHikeEndpointsLayer);
  }
  activeHikeRouteLayer = null;
  activeHikeRouteGlowLayer = null;
  activeHikeEndpointsLayer = null;
  mapEl?.classList.remove("hike-route-visible");
}

function createHikeEndpointMarker(role, latlng, label) {
  const isStart = role === "start";
  const fillColor = isStart ? "#15803d" : "#9a3412";
  const ringColor = isStart ? "#dcfce7" : "#fed7aa";
  const icon = L.divIcon({
    className: `hike-endpoint hike-endpoint-${role}`,
    html:
      `<span class="hike-endpoint__dot" style="--ring:${ringColor};--fill:${fillColor}">` +
      `<span class="hike-endpoint__label">${role === "start" ? "Start" : "Finish"}</span>` +
      `</span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11]
  });
  const marker = L.marker(latlng, {
    icon,
    pane: "hikeRouteActive",
    keyboard: false,
    zIndexOffset: isStart ? 1000 : 900,
    interactive: true
  });
  if (label) {
    marker.bindTooltip(label, { direction: "top", offset: [0, -10], opacity: 0.95 });
  }
  return marker;
}

async function showActiveHikeRoute(detail) {
  clearActiveHikeRoute();
  const raw = detail?.geometry;
  let geometry = raw;

  if (raw?.type === "LineString" && Array.isArray(raw.coordinates) && raw.coordinates.length >= 2) {
    try {
      const refined = await refineHikeTrailGeometry(raw.coordinates);
      if (refined?.coordinates?.length) {
        geometry = refined;
      }
    } catch (error) {
      console.warn("Trail geometry refine skipped:", error);
    }
  } else if (raw?.type === "MultiLineString" && Array.isArray(raw.coordinates)) {
    geometry = raw;
  }

  const hasLine =
    (geometry?.type === "LineString" && geometry.coordinates?.length >= 2) ||
    (geometry?.type === "MultiLineString" && geometry.coordinates?.some((ring) => ring.length >= 2));

  if (!hasLine) {
    return;
  }

  const routeStyle = {
    color: trailRouteStyle.line.color,
    weight: trailRouteStyle.line.weight,
    opacity: trailRouteStyle.line.opacity,
    lineCap: "round",
    lineJoin: "round"
  };

  activeHikeRouteGlowLayer = L.geoJSON(geometry, {
    pane: "hikeRouteGlow",
    style: {
      color: trailRouteStyle.glow.color,
      weight: trailRouteStyle.glow.weight,
      opacity: trailRouteStyle.glow.opacity,
      lineCap: "round",
      lineJoin: "round"
    },
    className: "hike-route-glow",
    interactive: false
  });

  activeHikeRouteLayer = L.geoJSON(geometry, {
    pane: "hikeRouteActive",
    style: routeStyle,
    className: "hike-route-active"
  });

  activeHikeRouteGlowLayer.addTo(map);
  activeHikeRouteLayer.addTo(map);

  const endpoints = [];
  if (Number.isFinite(detail?.start?.lat) && Number.isFinite(detail?.start?.lng)) {
    endpoints.push(
      createHikeEndpointMarker(
        "start",
        L.latLng(detail.start.lat, detail.start.lng),
        detail.start.name ? `Start: ${detail.start.name}` : "Trailhead"
      )
    );
  }
  if (
    Number.isFinite(detail?.end?.lat) &&
    Number.isFinite(detail?.end?.lng) &&
    (!detail.start ||
      detail.end.lat !== detail.start.lat ||
      detail.end.lng !== detail.start.lng)
  ) {
    endpoints.push(
      createHikeEndpointMarker(
        "end",
        L.latLng(detail.end.lat, detail.end.lng),
        detail.end.name ? `Finish: ${detail.end.name}` : "Trail end"
      )
    );
  }

  if (endpoints.length) {
    activeHikeEndpointsLayer = L.layerGroup(endpoints);
    activeHikeEndpointsLayer.addTo(map);
  }

  mapEl?.classList.add("hike-route-visible");
  refitActiveHikeRoute();
}

function createHikeCatalogMarker(props, lat, lng) {
  const marker = L.circleMarker([lat, lng], {
    pane: "hikesCatalog",
    radius: hikeCatalogRadius(props.tier),
    color: "#ffffff",
    weight: 1.5,
    fillColor: "#c2410c",
    fillOpacity: 0.94,
    opacity: 1,
    className: "hike-catalog-marker"
  });

  marker._hikeProps = props;
  marker.on("mousedown touchstart", L.DomEvent.stopPropagation);
  marker.on("click", (event) => {
    L.DomEvent.stopPropagation(event);
    if (typeof phoneMq === "function" && phoneMq()) {
      void showCatalogMarkerPreview(marker, "hike");
    } else {
      void openHikeFromMarker(marker);
    }
  });

  return marker;
}

async function refreshHikeCatalogMarkers() {
  if (!state.exploreHikes || !hikeCatalogLayer || !hikeCatalog) {
    return;
  }

  const bounds = map.getBounds();
  const zoom = map.getZoom();
  const fetchId = ++hikeCatalogFetchId;

  let geojson;
  try {
    geojson = await fetchHikeFeatures(
      hikeCatalog.id,
      {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth()
      },
      zoom
    );
  } catch (error) {
    console.warn("Hike features fetch failed:", error);
    return;
  }

  if (fetchId !== hikeCatalogFetchId || !state.exploreHikes) {
    return;
  }

  const visibleIds = new Set();
  const features = geojson?.features || [];

  features.forEach((feature) => {
    const props = feature.properties || {};
    const [lng, lat] = feature.geometry.coordinates;

    visibleIds.add(props.id);

    if (!hikeCatalogMarkersInView.has(props.id)) {
      const marker = createHikeCatalogMarker(props, lat, lng);
      hikeCatalogMarkersInView.set(props.id, marker);
      hikeCatalogLayer.addLayer(marker);
    }
  });

  hikeCatalogMarkersInView.forEach((marker, id) => {
    if (visibleIds.has(id) || id === activeHikeCatalogId) {
      return;
    }
    hikeCatalogLayer.removeLayer(marker);
    hikeCatalogMarkersInView.delete(id);
  });

  syncActiveHikeMarkerStyles();
}

function scheduleHikeCatalogRefresh() {
  if (!state.exploreHikes) {
    return;
  }
  if (activeHikeCatalogId) {
    return;
  }
  clearTimeout(hikeCatalogRefreshTimer);
  hikeCatalogRefreshTimer = setTimeout(() => {
    refreshHikeCatalogMarkers();
  }, 120);
}

function clearHikeCatalogMarkers() {
  hikeCatalogLayer?.clearLayers();
  hikeCatalogMarkersInView.clear();
}

function buildHikeCatalogLayer() {
  if (!hikeCatalog) {
    return;
  }

  if (!hikeCatalogLayer) {
    hikeCatalogLayer = L.layerGroup();
  } else {
    clearHikeCatalogMarkers();
  }

  bindExploreCatalogMapEvents();
  refreshHikeCatalogMarkers();
}

function parkCatalogRadius(tier) {
  if (tier === "major") {
    return 9 + TOUCH_HIT_BUMP;
  }
  if (tier === "regional") {
    return 7 + TOUCH_HIT_BUMP;
  }
  return 5 + TOUCH_HIT_BUMP;
}

function parkCatalogMarkerStyle(props, selected = false) {
  const tier = props.tier || "local";
  return {
    pane: "parksCatalog",
    radius: parkCatalogRadius(tier),
    color: "#ffffff",
    weight: selected ? 2.5 : 1.5,
    fillColor: tier === "major" ? "#15803d" : tier === "regional" ? "#16a34a" : "#22c55e",
    fillOpacity: selected ? 1 : 0.9,
    opacity: 1,
    className: selected ? "park-catalog-marker is-selected" : "park-catalog-marker"
  };
}

function syncActiveParkMarkerStyles() {
  parkCatalogMarkersInView.forEach((marker, id) => {
    const props = marker._parkProps;
    if (!props) {
      return;
    }
    const selected = id === activeParkCatalogId;
    marker.setStyle(parkCatalogMarkerStyle(props, selected));
  });
}

async function openParkFromMarker(marker) {
  const props = marker._parkProps;
  if (!props?.id) {
    return;
  }

  if (marker._parkOpening) {
    return;
  }

  marker._parkOpening = true;
  activeParkCatalogId = props.id;
  syncActiveParkMarkerStyles();
  map.closePopup();
  closeHikeStory();

  try {
    let details = marker._parkDetails;
    if (!details) {
      details = await fetchParkById(props.id);
      marker._parkDetails = details;
    }
    await openPlaceStory(details.name || props.name, details);
  } catch (error) {
    console.warn("Park detail fetch failed:", error);
    await openPlaceStory(props.name, { kind: "park", ...props });
  } finally {
    marker._parkOpening = false;
  }
}

function createParkCatalogMarker(props, lat, lng) {
  const selected = props.id === activeParkCatalogId;
  const marker = L.circleMarker([lat, lng], parkCatalogMarkerStyle(props, selected));

  marker._parkProps = props;
  marker.on("mousedown touchstart", L.DomEvent.stopPropagation);
  marker.on("click", (event) => {
    L.DomEvent.stopPropagation(event);
    if (typeof phoneMq === "function" && phoneMq()) {
      void showCatalogMarkerPreview(marker, "park");
    } else {
      void openParkFromMarker(marker);
    }
  });

  return marker;
}

async function refreshParkCatalogMarkers() {
  if (!state.exploreParks || !parkCatalogLayer || !parkCatalog) {
    return;
  }

  const bounds = map.getBounds();
  const zoom = map.getZoom();
  const fetchId = ++parkCatalogFetchId;

  let geojson;
  try {
    geojson = await fetchParkFeatures(
      parkCatalog.id,
      {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth()
      },
      zoom
    );
  } catch (error) {
    console.warn("Park features fetch failed:", error);
    return;
  }

  if (fetchId !== parkCatalogFetchId || !state.exploreParks) {
    return;
  }

  const visibleIds = new Set();
  const features = geojson?.features || [];

  features.forEach((feature) => {
    const props = feature.properties || {};
    const [lng, lat] = feature.geometry.coordinates;

    visibleIds.add(props.id);

    const existing = parkCatalogMarkersInView.get(props.id);
    if (!existing) {
      const marker = createParkCatalogMarker(props, lat, lng);
      parkCatalogMarkersInView.set(props.id, marker);
      parkCatalogLayer.addLayer(marker);
    } else {
      existing._parkProps = props;
      existing.setStyle(parkCatalogMarkerStyle(props, props.id === activeParkCatalogId));
    }
  });

  parkCatalogMarkersInView.forEach((marker, id) => {
    if (visibleIds.has(id) || id === activeParkCatalogId) {
      return;
    }
    parkCatalogLayer.removeLayer(marker);
    parkCatalogMarkersInView.delete(id);
  });

  syncActiveParkMarkerStyles();
}

function scheduleParkCatalogRefresh() {
  if (!state.exploreParks) {
    return;
  }
  if (activeParkCatalogId) {
    return;
  }
  clearTimeout(parkCatalogRefreshTimer);
  parkCatalogRefreshTimer = setTimeout(() => {
    refreshParkCatalogMarkers();
  }, 120);
}

function clearParkCatalogMarkers() {
  parkCatalogLayer?.clearLayers();
  parkCatalogMarkersInView.clear();
}

function buildParkCatalogLayer() {
  if (!parkCatalog) {
    return;
  }

  if (!parkCatalogLayer) {
    parkCatalogLayer = L.layerGroup();
  } else {
    clearParkCatalogMarkers();
  }

  bindExploreCatalogMapEvents();
  refreshParkCatalogMarkers();
}

function setExploreParks(enabled, options = {}) {
  const { keepDetailOpen = false } = options;
  state.exploreParks = enabled;
  const anyExplore = state.exploreCities || enabled || state.exploreHikes || state.explorePoi;
  document.body.classList.toggle("explore-mode-on", anyExplore);
  layoutRoot?.classList.toggle("map-stage--explore", anyExplore);

  if (enabled) {
    if (!parkCatalogLayer && parkCatalog) {
      buildParkCatalogLayer();
    }
    if (parkCatalogLayer && !map.hasLayer(parkCatalogLayer)) {
      parkCatalogLayer.addTo(map);
    }
    if (!countryRegionsLayer) {
      void initCountryBorders();
    } else {
      syncCountryRegionsLayer();
    }
    refreshParkCatalogMarkers();
    mapEl?.classList.add("explore-parks-on");
  } else {
    if (!keepDetailOpen) {
      const sheet = document.getElementById("placeStory");
      if (sheet?.classList.contains("is-open") && sheet.classList.contains("dest-panel--park")) {
        closePlaceStory();
      } else if (activeParkCatalogId) {
        activeParkCatalogId = null;
        syncActiveParkMarkerStyles();
      }
    }
    if (parkCatalogLayer && map.hasLayer(parkCatalogLayer)) {
      map.removeLayer(parkCatalogLayer);
    }
    clearParkCatalogMarkers();
    mapEl?.classList.remove("explore-parks-on");
    syncCountryRegionsLayer();
  }

  updateExploreParksUi();
  updateHudJourneyState();
}

function updateExploreParksUi() {
  const active = state.exploreParks === true;
  const chip = document.getElementById("exploreParksChip");
  if (chip) {
    chip.dataset.active = String(active);
    chip.setAttribute("aria-pressed", String(active));
  }
  syncExploreHudButton();
}

function renderExploreParksToggle() {
  const container = document.getElementById("exploreParksToggle");
  if (!container) {
    return;
  }

  const count = parkCatalog?.count || 0;
  const active = state.exploreParks === true;
  container.innerHTML = `
    <button
      type="button"
      id="exploreParksChip"
      class="layer-chip layer-chip--parks"
      data-active="${String(active)}"
      aria-pressed="${String(active)}"
      title="Show European national parks — tap for photos, biodiversity, and visitor tips"
    >Parks${count ? ` (${count.toLocaleString()})` : ""}</button>
  `;
  updateExploreParksUi();
}

function setupExploreParksToggle() {
  const row = document.getElementById("exploreLayersRow");
  if (!row || row.dataset.parksBound === "true") {
    return;
  }
  row.dataset.parksBound = "true";
  row.addEventListener("click", (event) => {
    if (event.target.closest("#exploreParksChip")) {
      setExploreParks(!state.exploreParks);
    }
  });
  renderExploreParksToggle();
}

async function initParkCatalog() {
  try {
    parkCatalog = await loadParkRegion("europe");
    renderExploreParksToggle();
  } catch (error) {
    console.warn("Park catalog not loaded:", error);
  }
}

function poiCatalogRadius(tier) {
  if (tier === "major") {
    return 9 + TOUCH_HIT_BUMP;
  }
  if (tier === "regional") {
    return 7 + TOUCH_HIT_BUMP;
  }
  return 6 + TOUCH_HIT_BUMP;
}

function poiCatalogMarkerStyle(props, selected = false) {
  const tier = props.tier || "local";
  return {
    pane: "poisCatalog",
    radius: poiCatalogRadius(tier),
    color: "#ffffff",
    weight: selected ? 2.5 : 1.5,
    fillColor: "#9333ea",
    fillOpacity: selected ? 1 : 0.92,
    opacity: 1,
    className: selected ? "poi-catalog-marker is-selected" : "poi-catalog-marker"
  };
}

function syncActivePoiMarkerStyles() {
  poiCatalogMarkersInView.forEach((marker, id) => {
    const props = marker._poiProps;
    if (!props) {
      return;
    }
    marker.setStyle(poiCatalogMarkerStyle(props, id === activePoiCatalogId));
  });
}

async function openPoiFromMarker(marker) {
  const props = marker._poiProps;
  if (!props?.id) {
    return;
  }

  if (marker._poiOpening) {
    return;
  }

  marker._poiOpening = true;
  activePoiCatalogId = props.id;
  syncActivePoiMarkerStyles();
  map.closePopup();
  closeHikeStory();

  try {
    let details = marker._poiDetails;
    if (!details) {
      details = await fetchPoiById(props.id);
      marker._poiDetails = details;
    }
    await openPlaceStory(details.name || props.name, details);
  } catch (error) {
    console.warn("POI detail fetch failed:", error);
    await openPlaceStory(props.name, { kind: "poi", ...props });
  } finally {
    marker._poiOpening = false;
  }
}

function createPoiCatalogMarker(props, lat, lng) {
  const selected = props.id === activePoiCatalogId;
  const marker = L.circleMarker([lat, lng], poiCatalogMarkerStyle(props, selected));

  marker._poiProps = props;
  marker.on("mousedown touchstart", L.DomEvent.stopPropagation);
  marker.on("click", (event) => {
    L.DomEvent.stopPropagation(event);
    if (typeof phoneMq === "function" && phoneMq()) {
      void showCatalogMarkerPreview(marker, "poi");
    } else {
      void openPoiFromMarker(marker);
    }
  });

  return marker;
}

async function refreshPoiCatalogMarkers() {
  if (!state.explorePoi || !poiCatalogLayer || !poiCatalog) {
    return;
  }

  const bounds = map.getBounds();
  const zoom = map.getZoom();
  const fetchId = ++poiCatalogFetchId;

  let geojson;
  try {
    geojson = await fetchPoiFeatures(
      poiCatalog.id,
      {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth()
      },
      zoom
    );
  } catch (error) {
    console.warn("POI features fetch failed:", error);
    return;
  }

  if (fetchId !== poiCatalogFetchId || !state.explorePoi) {
    return;
  }

  const visibleIds = new Set();
  const features = geojson?.features || [];

  features.forEach((feature) => {
    const props = feature.properties || {};
    const [lng, lat] = feature.geometry.coordinates;

    visibleIds.add(props.id);

    const existing = poiCatalogMarkersInView.get(props.id);
    if (!existing) {
      const marker = createPoiCatalogMarker(props, lat, lng);
      poiCatalogMarkersInView.set(props.id, marker);
      poiCatalogLayer.addLayer(marker);
    } else {
      existing._poiProps = props;
      existing.setStyle(poiCatalogMarkerStyle(props, props.id === activePoiCatalogId));
    }
  });

  poiCatalogMarkersInView.forEach((marker, id) => {
    if (visibleIds.has(id) || id === activePoiCatalogId) {
      return;
    }
    poiCatalogLayer.removeLayer(marker);
    poiCatalogMarkersInView.delete(id);
  });

  syncActivePoiMarkerStyles();
}

function schedulePoiCatalogRefresh() {
  if (!state.explorePoi) {
    return;
  }
  if (activePoiCatalogId) {
    return;
  }
  clearTimeout(poiCatalogRefreshTimer);
  poiCatalogRefreshTimer = setTimeout(() => {
    refreshPoiCatalogMarkers();
  }, 120);
}

function clearPoiCatalogMarkers() {
  poiCatalogLayer?.clearLayers();
  poiCatalogMarkersInView.clear();
}

function buildPoiCatalogLayer() {
  if (!poiCatalog) {
    return;
  }

  if (!poiCatalogLayer) {
    poiCatalogLayer = L.layerGroup();
  } else {
    clearPoiCatalogMarkers();
  }

  bindExploreCatalogMapEvents();
  refreshPoiCatalogMarkers();
}

function setExplorePoi(enabled, options = {}) {
  const { keepDetailOpen = false } = options;
  state.explorePoi = enabled;
  const anyExplore = state.exploreCities || state.exploreParks || state.exploreHikes || enabled;
  document.body.classList.toggle("explore-mode-on", anyExplore);
  layoutRoot?.classList.toggle("map-stage--explore", anyExplore);

  if (enabled) {
    if (!poiCatalogLayer && poiCatalog) {
      buildPoiCatalogLayer();
    }
    if (poiCatalogLayer && !map.hasLayer(poiCatalogLayer)) {
      poiCatalogLayer.addTo(map);
    }
    if (!countryRegionsLayer) {
      void initCountryBorders();
    } else {
      syncCountryRegionsLayer();
    }
    refreshPoiCatalogMarkers();
    mapEl?.classList.add("explore-pois-on");
  } else {
    if (!keepDetailOpen) {
      const sheet = document.getElementById("placeStory");
      if (sheet?.classList.contains("is-open") && sheet.classList.contains("dest-panel--poi")) {
        closePlaceStory();
      } else if (activePoiCatalogId) {
        activePoiCatalogId = null;
        syncActivePoiMarkerStyles();
      }
    }
    if (poiCatalogLayer && map.hasLayer(poiCatalogLayer)) {
      map.removeLayer(poiCatalogLayer);
    }
    clearPoiCatalogMarkers();
    mapEl?.classList.remove("explore-pois-on");
    syncCountryRegionsLayer();
  }

  updateExplorePoiUi();
  updateHudJourneyState();
}

function updateExplorePoiUi() {
  const active = state.explorePoi === true;
  const chip = document.getElementById("explorePoisChip");
  if (chip) {
    chip.dataset.active = String(active);
    chip.setAttribute("aria-pressed", String(active));
  }
  syncExploreHudButton();
}

function renderExplorePoisToggle() {
  const container = document.getElementById("explorePoisToggle");
  if (!container) {
    return;
  }

  const count = poiCatalog?.count || 0;
  const active = state.explorePoi === true;
  container.innerHTML = `
    <button
      type="button"
      id="explorePoisChip"
      class="layer-chip layer-chip--poi"
      data-active="${String(active)}"
      aria-pressed="${String(active)}"
      title="Historic sites, fortresses, famous mountains, and landmarks — purple markers"
    >Landmarks${count ? ` (${count.toLocaleString()})` : ""}</button>
  `;
  updateExplorePoiUi();
}

function setupExplorePoisToggle() {
  const row = document.getElementById("exploreLayersRow");
  if (!row || row.dataset.poisBound === "true") {
    return;
  }
  row.dataset.poisBound = "true";
  row.addEventListener("click", (event) => {
    if (event.target.closest("#explorePoisChip")) {
      setExplorePoi(!state.explorePoi);
    }
  });
  renderExplorePoisToggle();
}

async function initPoiCatalog() {
  try {
    poiCatalog = await loadPoiRegion("europe");
    renderExplorePoisToggle();
  } catch (error) {
    console.warn("POI catalog not loaded:", error);
  }
}

async function goToPoiFromSearch(poi) {
  if (!poi?.id || poi.lat == null || poi.lng == null) {
    return;
  }

  closeCitySearchResults();
  const input = document.getElementById("citySearchInput");
  if (input) {
    input.value = poi.name;
    const clearBtn = document.getElementById("citySearchClear");
    if (clearBtn) {
      clearBtn.hidden = false;
    }
  }

  dismissWelcomeOverlay();
  setActiveView("map", { silent: true });
  closeHikeStory();

  if (!state.explorePoi) {
    setExplorePoi(true, { keepDetailOpen: true });
  }

  await new Promise((resolve) => {
    const onEnd = () => {
      map.off("moveend", onEnd);
      resolve();
    };
    map.on("moveend", onEnd);
    map.flyTo([poi.lat, poi.lng], 10, { duration: 0.85 });
    window.setTimeout(() => {
      map.off("moveend", onEnd);
      resolve();
    }, 1400);
  });

  await refreshPoiCatalogMarkers();

  try {
    const details = await fetchPoiById(poi.id);
    await openPlaceStory(details.name || poi.name, details);
  } catch (error) {
    console.warn("POI search open failed:", error);
    await openPlaceStory(poi.name, { kind: "poi", ...poi });
  }
}

function setExploreHikes(enabled, options = {}) {
  const { keepDetailOpen = false } = options;
  state.exploreHikes = enabled;
  const anyExplore = state.exploreCities || state.exploreParks || state.explorePoi || enabled;
  document.body.classList.toggle("explore-mode-on", anyExplore);
  layoutRoot?.classList.toggle("map-stage--explore", anyExplore);

  if (enabled) {
    if (!keepDetailOpen) {
      closeHikeStory();
    }
    if (!hikeCatalogLayer && hikeCatalog) {
      buildHikeCatalogLayer();
    }
    if (hikeCatalogLayer && !map.hasLayer(hikeCatalogLayer)) {
      hikeCatalogLayer.addTo(map);
    }
    if (!countryRegionsLayer) {
      void initCountryBorders();
    } else {
      syncCountryRegionsLayer();
    }
    refreshHikeCatalogMarkers();
    mapEl?.classList.add("explore-hikes-on");
  } else {
    closeHikeStory();
    if (hikeCatalogLayer && map.hasLayer(hikeCatalogLayer)) {
      map.removeLayer(hikeCatalogLayer);
    }
    clearHikeCatalogMarkers();
    clearActiveHikeRoute();
    mapEl?.classList.remove("explore-hikes-on");
    syncCountryRegionsLayer();
  }

  updateExploreHikesUi();
}

function updateExploreHikesUi() {
  const active = state.exploreHikes === true;
  const chip = document.getElementById("exploreHikesChip");
  if (chip) {
    chip.dataset.active = String(active);
    chip.setAttribute("aria-pressed", String(active));
  }
  syncExploreHudButton();
}

function renderExploreHikesToggle() {
  const container = document.getElementById("exploreHikesToggle");
  if (!container) {
    return;
  }

  const count = hikeCatalog?.count || 0;
  const active = state.exploreHikes === true;
  container.innerHTML = `
    <button
      type="button"
      id="exploreHikesChip"
      class="layer-chip layer-chip--hikes"
      data-active="${String(active)}"
      aria-pressed="${String(active)}"
      title="Show European hiking trails — tap for route and trail details"
    >Trails${count ? ` (${count.toLocaleString()})` : ""}</button>
  `;
  updateExploreHikesUi();
}

function setupExploreHikesToggle() {
  const row = document.getElementById("exploreLayersRow");
  if (!row || row.dataset.hikesBound === "true") {
    return;
  }
  row.dataset.hikesBound = "true";
  row.addEventListener("click", (event) => {
    if (event.target.closest("#exploreHikesChip")) {
      setExploreHikes(!state.exploreHikes);
    }
  });
  renderExploreHikesToggle();
}

async function initHikeCatalog() {
  try {
    hikeCatalog = await loadHikeRegion("europe");
    renderExploreHikesToggle();
  } catch (error) {
    console.warn("Hike catalog not loaded:", error);
  }
}

function pointPopupHtml(props) {
  const title = props.name || "Stop";
  const details = getPlaceDetail(title);
  const countryLabel = details.country || props.country || "";
  const dayText = props.day ? `<span class="dest-popup-card__day">Day ${escapeHtml(props.day)}</span>` : "";
  const photoCount = getPlacePhotos(title).length;
  const flagUrl = countryFlagUrl(countryLabel);
  const heroPhoto = normalizePhotoEntries(details.photos)[0];
  const heroImg = buildPopupHeroImageTag(heroPhoto, title);
  const typeLabel = (() => {
    const cat = details.category;
    if (cat) {
      if (details.kind === "park") {
        return parkCategoryLabel(cat);
      }
      if (details.kind === "poi") {
        return poiCategoryLabel(cat);
      }
      if (CITY_CATEGORY_KEYS.has(cat)) {
        return cityCategoryLabel(cat, details.locale);
      }
      if (PARK_CATEGORY_KEYS.has(cat)) {
        return parkCategoryLabel(cat);
      }
      if (POI_CATEGORY_KEYS.has(cat)) {
        return poiCategoryLabel(cat);
      }
    }
    const stop = journeyStopType(props);
    return stop ? stopTypeLabel(stop) : "";
  })();
  const typeChip = typeLabel
    ? `<span class="dest-popup-card__day">${escapeHtml(typeLabel)}</span>`
    : "";

  return `
    <div class="marker-popup marker-popup-rich dest-popup-card" data-place-name="${escapeHtml(title)}">
      <div class="dest-popup-card__hero${heroImg ? " dest-popup-card__hero--has-photo" : ""}">
        ${heroImg}
        <div class="dest-popup-card__hero-overlay">
          <div class="dest-popup-card__hero-gradient"></div>
          ${flagUrl ? `<img class="dest-popup-card__flag" src="${escapeAttr(flagUrl)}" alt="" width="14" height="14" loading="lazy" referrerpolicy="no-referrer" />` : ""}
          <h4 class="dest-popup-card__title">${escapeHtml(title)}</h4>
          <p class="dest-popup-card__tagline">${escapeHtml(placeTagline(details))}</p>
        </div>
      </div>
      <div class="dest-popup-card__body">
        ${countryLabel ? `<span class="dest-popup-card__country">${escapeHtml(countryLabel)}</span>` : ""}
        ${typeChip}
        ${dayText}
        <button type="button" class="popup-story-btn" data-place-story data-place-title="${escapeHtml(title)}">
          View destination${photoCount > 0 ? ` · ${photoCount} photos` : ""}
        </button>
      </div>
    </div>
  `;
}

function applyBasemapClass(basemapKey) {
  if (!mapEl) {
    return;
  }

  Object.keys(basemapConfig).forEach((key) => {
    mapEl.classList.remove(`basemap-${key}`);
  });
  mapEl.classList.add(`basemap-${basemapKey}`);
}

function updateLayerChipUI() {
  document.querySelectorAll("button[data-basemap]").forEach((button) => {
    const active = button.dataset.basemap === state.basemap;
    button.dataset.active = String(active);
    button.setAttribute("aria-pressed", String(active));
  });

  document.querySelectorAll("button[data-overlay]").forEach((button) => {
    const key = button.dataset.overlay;
    const active = state.overlays[key] === true;
    button.dataset.active = String(active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setOverlay(key, enabled) {
  const layer = overlayLayers[key];
  if (!layer) {
    return;
  }

  state.overlays[key] = enabled;

  if (enabled) {
    if (!map.hasLayer(layer)) {
      layer.addTo(map);
    }
  } else if (map.hasLayer(layer)) {
    map.removeLayer(layer);
  }

  updateLayerChipUI();
}

function setBasemap(key) {
  const layer = basemapLayers[key];
  if (!layer) {
    return;
  }

  if (state.basemap === key && activeBasemapLayer && map.hasLayer(activeBasemapLayer)) {
    return;
  }

  mapEl?.classList.add("basemap-transitioning");

  if (activeBasemapLayer && map.hasLayer(activeBasemapLayer)) {
    map.removeLayer(activeBasemapLayer);
  }

  activeBasemapLayer = layer;
  layer.addTo(map);
  layer.bringToBack();

  state.basemap = key;
  applyBasemapClass(key);
  updateLayerChipUI();

  if (key === "satellite" && !state.overlays.labels) {
    setOverlay("labels", true);
  }

  window.setTimeout(() => {
    mapEl?.classList.remove("basemap-transitioning");
    map.invalidateSize();
  }, 320);
}

function renderBasemapSwitcher() {
  const container = document.getElementById("basemapSwitcher");
  if (!container) {
    return;
  }

  container.innerHTML = Object.entries(basemapConfig)
    .map(([key, item]) => {
      const active = state.basemap === key;
      return `
        <button
          type="button"
          class="layer-chip layer-chip--basemap"
          data-basemap="${key}"
          data-active="${String(active)}"
          aria-pressed="${String(active)}"
          title="${item.hint}"
        >${item.label}</button>
      `;
    })
    .join("");

  container.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-basemap]");
    if (!button) {
      return;
    }
    setBasemap(button.dataset.basemap);
  });
}

function renderOverlaySwitcher() {
  const container = document.getElementById("overlaySwitcher");
  if (!container) {
    return;
  }

  container.innerHTML = Object.entries(overlayConfig)
    .map(([key, item]) => {
      const active = state.overlays[key] === true;
      return `
        <button
          type="button"
          class="layer-chip layer-chip--overlay"
          data-overlay="${key}"
          data-active="${String(active)}"
          aria-pressed="${String(active)}"
          title="${item.hint}"
        >${item.label}</button>
      `;
    })
    .join("");

  container.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-overlay]");
    if (!button) {
      return;
    }

    const key = button.dataset.overlay;
    setOverlay(key, !state.overlays[key]);
  });
}

function setupMapLayers() {
  setBasemap(state.basemap);
  Object.entries(state.overlays).forEach(([key, enabled]) => {
    if (enabled) {
      setOverlay(key, true);
    }
  });
}

function renderLegend() {
  const legend = document.getElementById("routeLegend");
  // render legend as interactive buttons that toggle mode visibility
  legend.innerHTML = Object.entries(modeConfig)
    .map(([key, mode]) => `
      <button class="legend-chip" data-type="modes" data-key="${key}" data-active="true" aria-pressed="true" title="Toggle ${mode.label}">
        <span class="swatch" style="background:${mode.color}"></span>${mode.label}
      </button>
    `)
    .join("");

  legend.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-key]");
    if (!button) return;

    const key = button.dataset.key;
    const active = state.modes[key] !== false;
    const activeCount = Object.values(state.modes).filter(Boolean).length;
    if (active && activeCount === 1) {
      return; // prevent disabling the last active mode
    }

    state.modes[key] = !active;
    updateToggleUI();
    applyFilters();
  });
}

function updateToggleUI() {
  const buttons = document.querySelectorAll("button[data-type][data-key]");
  buttons.forEach((button) => {
    const type = button.dataset.type;
    const key = button.dataset.key;
    const active = state[type][key] !== false;
    button.dataset.active = String(active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setLayerVisibility(layer, visible) {
  if (visible && !map.hasLayer(layer)) {
    layer.addTo(map);
  }

  if (!visible && map.hasLayer(layer)) {
    map.removeLayer(layer);
  }
}

function layerVisibleByFilters(meta) {
  return meta.mode ? state.modes[meta.mode] !== false : true;
}

function applyFilters(fit = false) {
  const visibleBounds = L.latLngBounds([]);

  lineEntries.forEach((entry) => {
    const visible = layerVisibleByFilters(entry.meta);
    setLayerVisibility(entry.glowLayer, visible);
    setLayerVisibility(entry.lineLayer, visible);
    if (visible) {
      visibleBounds.extend(entry.lineLayer.getBounds());
    }
  });

  pointEntries.forEach((entry) => {
    const visible = layerVisibleByFilters(entry.meta);
    setLayerVisibility(entry.marker, visible);
    if (visible) {
      visibleBounds.extend(entry.marker.getLatLng());
    }
  });

  if (fit && visibleBounds.isValid()) {
    // fit bounds with reasonable max zoom to prevent excessive zooming and clipping
    map.fitBounds(visibleBounds.pad(0.12), {
      maxZoom: 16,
      padding: [40, 40],
      duration: 500
    });
  }
}

function clearTripLayers() {
  lineEntries.forEach((entry) => {
    map.removeLayer(entry.glowLayer);
    map.removeLayer(entry.lineLayer);
  });

  pointEntries.forEach((entry) => {
    map.removeLayer(entry.marker);
  });

  lineEntries.length = 0;
  pointEntries.length = 0;
}

function endpointsFromLegName(name) {
  if (typeof name !== "string" || !name) {
    return [];
  }
  const cleaned = name
    .replace(/\b(via|through|across|along|by|train|ferry|drive|flight|hike|route|coastal|spine|leg|segment)\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned
    .split(/\s+to\s+/i)
    .map((part) => part.trim())
    .filter((part) => part.length > 1 && /[A-Za-zÀ-ÿ]/.test(part));
}

function linePopupThumbForProps(props, mode) {
  const candidates = [];
  const tryPushPhoto = (name) => {
    if (!name) return;
    const photos = getPlacePhotos(name);
    if (photos.length) candidates.push({ url: photos[0].url, caption: name });
  };
  tryPushPhoto(props.from);
  tryPushPhoto(props.to);
  if (!candidates.length) {
    const parts = endpointsFromLegName(props.name);
    parts.slice(0, 2).forEach(tryPushPhoto);
  }
  if (!candidates.length) {
    const trip = state.trips.find((t) => t.key === state.selectedTrip);
    if (trip?.cover) {
      candidates.push({ url: trip.cover, caption: trip.title });
    } else if (trip?.gallery?.[0]?.url) {
      candidates.push({ url: trip.gallery[0].url, caption: trip.gallery[0].caption || trip.title });
    }
  }
  const pick = candidates.find((c) => c.url);
  if (!pick) {
    return "";
  }
  return `
    <div class="route-leg-popup__thumb">
      <img src="${escapeHtml(pick.url)}" alt="${escapeHtml(pick.caption || "")}" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.closest('.route-leg-popup__thumb')?.remove()" />
      <span class="route-leg-popup__mode-pill" data-mode="${escapeHtml(mode)}">${escapeHtml(modeLabel(mode))}</span>
    </div>
  `;
}

function linePopupHtml(props, mode) {
  const title = escapeHtml(props.name || modeLabel(mode));
  const route = props.from && props.to
    ? `<div class="route-leg-popup__from-to"><span>${escapeHtml(props.from)}</span><span class="route-leg-popup__arrow" aria-hidden="true">→</span><span>${escapeHtml(props.to)}</span></div>`
    : "";
  const dayChip = props.day
    ? `<span class="route-leg-popup__chip route-leg-popup__chip--day">Day ${escapeHtml(String(props.day))}</span>`
    : "";
  const distChip = props.distanceKm != null
    ? `<span class="route-leg-popup__chip route-leg-popup__chip--dist">${escapeHtml(String(props.distanceKm))} km</span>`
    : "";
  const durationChip = props.durationMin
    ? `<span class="route-leg-popup__chip route-leg-popup__chip--time">${escapeHtml(formatDurationLabel(props.durationMin))}</span>`
    : "";
  const networkHint =
    mode === "hike" && props.hikeId
      ? "Hiking trail catalog · OpenStreetMap"
      : mode === "hike"
        ? "Footpaths · OpenStreetMap"
        : mode === "drive"
        ? "Road network · OSRM"
        : mode === "train" && props.transitRouteId
          ? "Rail network · OpenStreetMap"
          : mode === "ferry"
            ? "Ferry route · OpenStreetMap"
            : mode === "fly"
              ? "Direct flight · great-circle path"
              : "";
  const source = props.routeSource
    ? `<div class="route-leg-popup__source">${escapeHtml(props.routeSource)}</div>`
    : "";
  const network = networkHint
    ? `<div class="route-leg-popup__network">${escapeHtml(networkHint)}</div>`
    : "";
  const chips = [dayChip, distChip, durationChip].filter(Boolean).join("");

  return `
    <div class="marker-popup route-leg-popup">
      ${linePopupThumbForProps(props, mode)}
      <div class="route-leg-popup__body">
        <strong class="route-leg-popup__title">${title}</strong>
        ${route}
        ${chips ? `<div class="route-leg-popup__chips">${chips}</div>` : ""}
        ${network}
        ${source}
      </div>
    </div>
  `;
}

function formatDurationLabel(minutes) {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

function primaryLineGeometry(geometry) {
  if (!geometry) {
    return null;
  }
  if (geometry.type === "LineString" && geometry.coordinates?.length >= 2) {
    return geometry;
  }
  if (geometry.type === "MultiLineString" && geometry.coordinates?.length) {
    const rings = geometry.coordinates.filter((ring) => ring.length >= 2);
    if (!rings.length) {
      return null;
    }
    const longest = rings.reduce((best, ring) => (ring.length > best.length ? ring : best), rings[0]);
    return { type: "LineString", coordinates: longest };
  }
  return null;
}

function lineCoordsToLatLngs(feature) {
  const geometry = primaryLineGeometry(feature?.geometry) || feature?.geometry;
  return (geometry?.coordinates || []).map(([lng, lat]) => L.latLng(lat, lng));
}

function updateLineEntryGeometry(entry, feature) {
  const latlngs = lineCoordsToLatLngs(feature);
  if (!latlngs.length) {
    return;
  }

  const mode = feature?.properties?.mode || entry.meta.mode || "drive";
  const props = feature.properties || {};

  entry.glowLayer.eachLayer((layer) => {
    if (typeof layer.setLatLngs === "function") {
      layer.setLatLngs(latlngs);
    }
  });

  entry.lineLayer.eachLayer((layer) => {
    if (typeof layer.setLatLngs === "function") {
      layer.setLatLngs(latlngs);
    }
    if (typeof layer.setPopupContent === "function") {
      layer.setPopupContent(linePopupHtml(props, mode));
    }
  });
}

async function resolveTransitLines(lineFeatures) {
  let catalog;
  try {
    catalog = await loadTransitRoutesCatalog();
  } catch (error) {
    console.warn("Transit route catalog unavailable:", error);
    return lineFeatures.filter((feature) => feature?.properties?.mode !== "train");
  }

  const resolved = [];
  for (const feature of lineFeatures) {
    if (feature?.properties?.mode !== "train") {
      resolved.push(feature);
      continue;
    }

    const transitRouteId = feature?.properties?.transitRouteId;
    const route = transitRouteFromCatalog(catalog, transitRouteId);
    if (!route) {
      console.warn("Skipping train leg without OSM rail route:", feature?.properties?.name, transitRouteId);
      continue;
    }

    resolved.push({
      ...feature,
      geometry: {
        type: "LineString",
        coordinates: route.coordinates
      },
      properties: {
        ...feature.properties,
        distanceKm: route.lengthKm,
        routeSource: route.source || "OpenStreetMap rail network",
        osmTransit: true
      }
    });
  }

  return resolved;
}

async function resolveFerryLines(lineFeatures) {
  let catalog;
  try {
    catalog = await loadFerryRoutesCatalog();
  } catch (error) {
    console.warn("Ferry route catalog unavailable:", error);
    return lineFeatures.filter((feature) => feature?.properties?.mode !== "ferry");
  }

  const resolved = [];
  for (const feature of lineFeatures) {
    if (feature?.properties?.mode !== "ferry") {
      resolved.push(feature);
      continue;
    }

    const ferryRouteId = feature?.properties?.ferryRouteId;
    const route = ferryRouteFromCatalog(catalog, ferryRouteId);
    if (!route) {
      console.warn("Skipping ferry leg without OSM route:", feature?.properties?.name, ferryRouteId);
      continue;
    }

    resolved.push({
      ...feature,
      geometry: {
        type: "LineString",
        coordinates: route.coordinates
      },
      properties: {
        ...feature.properties,
        distanceKm: route.lengthKm,
        routeSource: route.source || "OpenStreetMap ferry network",
        osmFerry: true
      }
    });
  }

  return resolved;
}

async function resolveJourneyHikeLines(lineFeatures) {
  const resolved = [];

  for (const feature of lineFeatures) {
    const mode = feature?.properties?.mode;
    if (mode !== "hike") {
      resolved.push(feature);
      continue;
    }

    const hikeId = feature?.properties?.hikeId;
    if (!hikeId) {
      console.warn("Skipping journey leg without catalog trail:", feature?.properties?.name);
      continue;
    }

    try {
      const detail = await fetchHikeById(hikeId);
      let geometry = primaryLineGeometry(detail?.geometry) || detail?.geometry;
      if (geometry?.type === "LineString" && geometry.coordinates?.length >= 2) {
        try {
          const refined = await refineHikeTrailGeometry(geometry.coordinates);
          geometry = primaryLineGeometry(refined) || refined || geometry;
        } catch (error) {
          console.warn("Trail refine skipped:", hikeId, error);
        }
      }

      if (!geometry?.coordinates?.length || geometry.coordinates.length < 2) {
        console.warn("Catalog trail has no line geometry:", hikeId);
        continue;
      }

      resolved.push({
        ...feature,
        geometry,
        properties: {
          ...feature.properties,
          name: detail.name || feature.properties?.name,
          hikeId,
          catalogTrail: true,
          lengthKm: detail.length_km ?? feature.properties?.lengthKm,
          routeSource: `${detail.name || "Trail"} · OpenStreetMap hiking trail`
        }
      });
    } catch (error) {
      console.warn("Could not load catalog trail for journey leg:", hikeId, error);
    }
  }

  return resolved;
}

function createLineLayers(features) {
  features.forEach((feature) => {
    const mode = feature?.properties?.mode || "drive";
    const props = feature?.properties || {};
    const section = classifyLineSection(feature);
    const lineKey = lineFeatureKey(feature);

    const glowLayer = L.geoJSON(feature, {
      pane: "routeGlow",
      interactive: false,
      style: () => pathGlowStyleByMode(mode, props)
    });

    const lineLayer = L.geoJSON(feature, {
      pane: "routeLine",
      style: () => pathStyleByMode(mode, props),
      onEachFeature: (currentFeature, featureLayer) => {
        const props = currentFeature.properties || {};
        featureLayer.bindPopup(linePopupHtml(props, mode));
      }
    });

    lineEntries.push({
      glowLayer,
      lineLayer,
      meta: {
        mode,
        section,
        lineKey
      }
    });
  });
}

function normalizeTripAssetPath(path) {
  if (!path) {
    return path;
  }
  return path.replace(/^\.\//, "");
}

async function fetchTripGeojson(tripKey, geojsonPath) {
  if (tripGeojsonCache.has(tripKey)) {
    return tripGeojsonCache.get(tripKey);
  }

  const fetchPath = normalizeTripAssetPath(geojsonPath);
  const response = await fetch(fetchPath);
  if (!response.ok) {
    throw new Error(`Could not load route data (${response.status})`);
  }

  const geojson = await response.json();
  tripGeojsonCache.set(tripKey, geojson);
  return geojson;
}

function prefetchTrip(tripKey) {
  const trip = state.trips.find((item) => item.key === tripKey);
  if (!trip || tripGeojsonCache.has(tripKey) || tripPrefetchInFlight.has(tripKey)) {
    return;
  }

  const geojsonPath = trip.route || trip.geojson;
  const itineraryPath = normalizeTripAssetPath(trip.itineraryFile || trip.itinerary);

  const geoPromise = fetchTripGeojson(tripKey, geojsonPath).catch(() => null);
  tripPrefetchInFlight.set(tripKey, geoPromise);

  void fetch(itineraryPath).catch(() => null);

  geoPromise.finally(() => {
    tripPrefetchInFlight.delete(tripKey);
  });
}

async function enrichTripLinesInBackground(lineFeatures, generation) {
  if (!lineFeatures.length) {
    return;
  }

  try {
    const enriched = await enrichTripLineFeatures(lineFeatures, { concurrency: 4 });
    if (generation !== tripEnrichGeneration) {
      return;
    }

    const byKey = new Map(
      enriched
        .filter((feature) => feature?.geometry?.type === "LineString")
        .map((feature) => [lineFeatureKey(feature), feature])
    );

    lineEntries.forEach((entry) => {
      const feature = byKey.get(entry.meta.lineKey);
      if (feature) {
        updateLineEntryGeometry(entry, feature);
      }
    });
  } catch (error) {
    console.warn("Route enrichment skipped:", error);
  }
}

function createPointLayers(features) {
  features.forEach((feature) => {
    const [lng, lat] = feature.geometry.coordinates;
    const props = feature.properties || {};
    const stopType = journeyStopType(props);
    const section = classifyPointSection(feature);

    const marker = L.circleMarker([lat, lng], {
      pane: "routeMarkers",
      radius: 9,
      color: "#ffffff",
      weight: 2,
      fillColor: stopColor(stopType),
      fillOpacity: 1,
      opacity: 1
    });

    marker._tripProps = { ...props, stopType };
    marker.on("mousedown touchstart", L.DomEvent.stopPropagation);
    marker.bindPopup(pointPopupHtml(props), {
      maxWidth: 320,
      minWidth: 260,
      autoPan: true,
      autoPanPaddingTopLeft: L.point(24, 24),
      autoPanPaddingBottomRight: L.point(24, 160)
    });

    pointEntries.push({
      marker,
      props,
      meta: {
        section
      }
    });
  });
}

function buildTripGalleryPhotos(trip, pointFeatures) {
  const photos = [];
  const seen = new Set();

  const push = (entry) => {
    if (!entry?.url || seen.has(entry.url)) {
      return;
    }
    seen.add(entry.url);
    photos.push(entry);
  };

  (trip.gallery || []).forEach((item) => {
    push(typeof item === "string" ? { url: item, caption: trip.title } : item);
  });

  if (trip.cover) {
    push({ url: trip.cover, caption: trip.title });
  }

  pointFeatures.forEach((feature) => {
    const name = feature.properties?.name;
    if (!name) {
      return;
    }
    getPlacePhotos(name)
      .slice(0, 2)
      .forEach((photo) => {
        push({ url: photo.url, caption: photo.caption || name });
      });
  });

  return photos.slice(0, 8);
}

function renderTripGallery(trip, pointFeatures) {
  const host = document.getElementById("tripGallery");
  if (!host) {
    return;
  }

  const header = host.closest(".journey-panel-header");
  const photos = buildTripGalleryPhotos(trip, pointFeatures);
  if (!photos.length) {
    host.hidden = true;
    host.setAttribute("aria-hidden", "true");
    host.innerHTML = "";
    header?.classList.remove("journey-panel-header--with-gallery");
    requestAnimationFrame(updateLayoutInsets);
    return;
  }

  host.hidden = false;
  host.setAttribute("aria-hidden", "false");
  host.innerHTML = buildMediaCarouselHtml(photos, { variant: "trip", title: trip.title });
  initMediaCarousels(host);
  header?.classList.add("journey-panel-header--with-gallery");
  requestAnimationFrame(updateLayoutInsets);
}

function updateTripHeader(trip, features) {
  const daysEl = document.getElementById("statDays");
  const modesEl = document.getElementById("statModes");
  const stopsEl = document.getElementById("statStops");
  const titleEl = document.getElementById("tripTitle");
  const descEl = document.getElementById("tripDescription");

  const pointFeatures = features.filter((feature) => feature?.geometry?.type === "Point");
  const pointCount = pointFeatures.length;
  const modeSet = new Set(features.filter((feature) => feature?.geometry?.type === "LineString").map((feature) => feature?.properties?.mode || "drive"));

  titleEl.textContent = trip.title;

  let description = trip.description;
  if (trip.budgetAudMin && trip.budgetAudMax) {
    description += ` · Budget ${formatAud(trip.budgetAudMin)}–${formatAud(trip.budgetAudMax).replace(/^AUD /, "")}`;
  }
  descEl.textContent = description;

  daysEl.textContent = `${trip.days} Days`;
  modesEl.textContent = trip.distanceKm ? `${trip.distanceKm} km` : `${modeSet.size} Modes`;
  stopsEl.textContent = `${pointCount} Stops`;

  renderTripGallery(trip, pointFeatures);

  const regionEl = document.getElementById("tripRegion");
  if (regionEl) {
    if (trip.region) {
      regionEl.hidden = false;
      regionEl.textContent = trip.region;
    } else {
      regionEl.hidden = true;
      regionEl.textContent = "";
    }
  }

  const highlightsEl = document.getElementById("tripHighlights");
  const highlights = trip.highlights || [];
  if (highlightsEl) {
    if (highlights.length) {
      highlightsEl.hidden = false;
      highlightsEl.innerHTML = highlights.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    } else {
      highlightsEl.hidden = true;
      highlightsEl.innerHTML = "";
    }
  }

  animateHudTitle(trip.title);

  itineraryPanel?.classList.remove("journey-panel--empty");
  journeyEmptyState?.setAttribute("hidden", "");
  tripQuickStats?.removeAttribute("hidden");
  document.getElementById("itineraryContent")?.removeAttribute("hidden");

  updateHudJourneyState();
  syncHudNavAvailability();
  syncRouteControlsVisibility();
}

function renderInlineItinerary(trip) {
  const content = document.getElementById("itineraryContent");
  if (!content) {
    return;
  }
  const highlights = (trip.highlights || [])
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");
  const shareLine = trip.sharedCode
    ? `<p class="itinerary-share">Shared journey code: <strong>${escapeHtml(trip.sharedCode)}</strong>${trip.author ? ` · by ${escapeHtml(trip.author)}` : ""}</p>`
    : "";
  content.innerHTML = `
    ${shareLine}
    <p>${escapeHtml(trip.description || "")}</p>
    ${highlights ? `<h3>Highlights</h3><ul>${highlights}</ul>` : ""}
    <p class="itinerary-share itinerary-share--hint">Use the map to follow the route — share the code with friends to send them this journey.</p>
  `;
}

async function loadItinerary(path, { animate = true } = {}) {
  const content = document.getElementById("itineraryContent");
  if (!content) {
    return;
  }

  const fetchPath = normalizeTripAssetPath(path);
  let response;
  try {
    response = await fetch(fetchPath);
  } catch (error) {
    console.error("Itinerary fetch failed:", error);
    content.innerHTML = "<p class=\"itinerary-error\">Could not load itinerary.</p>";
    return;
  }

  if (!response.ok) {
    content.innerHTML = `<p class="itinerary-error">Could not load itinerary (${response.status}).</p>`;
    return;
  }

  if (animate) {
    content.classList.add("is-swapping");
    await wait(140);
  }

  let markdown;
  try {
    markdown = await response.text();
  } catch (error) {
    console.error("Itinerary read failed:", error);
    content.innerHTML = "<p class=\"itinerary-error\">Could not read itinerary file.</p>";
    return;
  }

  marked.setOptions({
    gfm: true,
    breaks: true
  });

  try {
    content.innerHTML = convertItineraryHtmlToAud(marked.parse(markdown));
    enhanceItineraryContent(content);
  } catch (error) {
    console.error("Itinerary render failed:", error);
    content.innerHTML = "<p class=\"itinerary-error\">Could not render itinerary content.</p>";
    return;
  }

  try {
    decorateItineraryPlaces(content, { placeDetails, getPlacePhoto });
  } catch (error) {
    console.warn("Itinerary photo decoration skipped:", error);
  }

  if (animate) {
    content.classList.remove("is-swapping");
    content.classList.add("is-revealing");
    window.setTimeout(() => {
      content.classList.remove("is-revealing");
      updateLayoutInsets();
    }, 360);
  } else {
    requestAnimationFrame(updateLayoutInsets);
  }
}

function setupItineraryInteractions() {
  const content = document.getElementById("itineraryContent");
  if (!content || content.dataset.itineraryBound === "true") {
    return;
  }

  content.dataset.itineraryBound = "true";

  content.addEventListener("click", (event) => {
    const card = event.target.closest(".itinerary-day-card[data-place-name]");
    if (!card) {
      return;
    }
    event.preventDefault();
    const name = card.dataset.placeName;
    flyToStop(name);
    const entry = pointEntries.find((item) => item.props?.name === name);
    openPlaceStory(name, entry?.props || {});
  });

  content.addEventListener("keydown", (event) => {
    const card = event.target.closest(".itinerary-day-card[data-place-name]");
    if (!card || (event.key !== "Enter" && event.key !== " ")) {
      return;
    }
    event.preventDefault();
    card.click();
  });
}

function setupMapPopups() {
  // Tapping the map background minimises the journey panel so the user can
  // see what they tapped. Marker / control / popup clicks don't bubble to the
  // map "click" event in Leaflet, so this only fires for real background taps.
  map.on("click", () => {
    const panel = document.getElementById("itineraryPanel");
    if (!panel) return;
    const expandedOnPhone = phoneMq() && panel.classList.contains("is-expanded");
    const openOnDesktop = !phoneMq() && !panelCollapsed && hasActiveJourney();
    if (!expandedOnPhone && !openOnDesktop) return;
    setPanelCollapsed(true);
    if (phoneMq()) updateMobileBottomNavActive();
  });

  map.on("popupopen", (event) => {
    activeMapPopup = event.popup;
    const root = event.popup.getElement();
    if (root) {
      L.DomEvent.disableClickPropagation(root);
      L.DomEvent.disableScrollPropagation(root);
      initMediaCarousels(root);
      if (!isCityCatalogMarker(event.popup?._source)) {
        refreshMapPopupLayout();
      }
    }
    // If a lingering hike route is still painted (panel was dismissed with
    // keepRoute: true) and the user now interacts with a non-hike marker,
    // wipe the trail so the new selection isn't visually crowded.
    const content = event.popup?.getContent?.();
    const isHikePreview =
      typeof content === "string" && content.includes('data-marker-kind="hike"');
    if (!isHikePreview && activeHikeRouteLayer && !isHikeStoryVisible()) {
      clearActiveHikeRoute();
      activeHikeCatalogId = null;
      syncActiveHikeMarkerStyles();
    }
    syncMapPopupStacking();
    requestAnimationFrame(() => {
      syncMapPopupStacking();
      event.popup?.update();
    });
  });

  map.on("popupclose", (event) => {
    activeMapPopup = null;
    if (isCityCatalogMarker(event.popup?._source)) {
      activeCityCatalogId = null;
    }
    const root = event.popup?.getContent?.();
    if (!catalogPreviewTransitioning && typeof root === "string") {
      if (root.includes('data-marker-kind="hike"')) {
        if (!isHikeStoryVisible()) {
          clearActiveHikeRoute();
          activeHikeCatalogId = null;
          syncActiveHikeMarkerStyles();
        }
      } else if (root.includes('data-marker-kind="park"')) {
        if (activeParkCatalogId) {
          activeParkCatalogId = null;
          syncActiveParkMarkerStyles();
        }
      } else if (root.includes('data-marker-kind="poi"')) {
        if (activePoiCatalogId) {
          activePoiCatalogId = null;
          syncActivePoiMarkerStyles();
        }
      }
    }
    requestAnimationFrame(syncMapPopupStacking);
  });

  map.getContainer().addEventListener("click", (event) => {
    const previewBtn = event.target.closest("[data-marker-action]");
    if (previewBtn) {
      event.preventDefault();
      event.stopPropagation();
      L.DomEvent.stopPropagation(event);
      const kind = previewBtn.dataset.markerKind;
      const id = previewBtn.dataset.markerId;
      const lookup = {
        hike: hikeCatalogMarkersInView,
        park: parkCatalogMarkersInView,
        poi: poiCatalogMarkersInView
      }[kind];
      const marker = lookup?.get?.(id);
      if (!marker) return;
      catalogPreviewTransitioning = true;
      map.closePopup();
      catalogPreviewTransitioning = false;
      if (kind === "hike") {
        void openHikeFromMarker(marker);
      } else if (kind === "park") {
        void openParkFromMarker(marker);
      } else if (kind === "poi") {
        void openPoiFromMarker(marker);
      }
      return;
    }

    const storyBtn = event.target.closest("[data-place-story]");
    if (!storyBtn) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    L.DomEvent.stopPropagation(event);
    const root = storyBtn.closest(".marker-popup-rich");
    const title = storyBtn.dataset.placeTitle || root?.dataset.placeName;
    if (!title) {
      return;
    }

    const entry = pointEntries.find((item) => item.props?.name === title);
    openPlaceStory(title, entry?.props || {});
  });
}

async function loadTrip(tripKey, fit = true, { animate = true } = {}) {
  const trip = state.trips.find((item) => item.key === tripKey);
  if (!trip) {
    return;
  }

  const enrichGeneration = ++tripEnrichGeneration;
  state.selectedTrip = tripKey;
  dismissWelcomeOverlay();

  const geojsonPath = trip.route || trip.geojson;
  const itineraryPath = trip.itineraryFile || trip.itinerary;

  if (animate) {
    layoutRoot?.classList.add("is-trip-loading");
  }

  let geojson;
  try {
    const [geojsonResult] = await Promise.all([
      fetchTripGeojson(tripKey, geojsonPath),
      itineraryPath
        ? loadItinerary(itineraryPath, { animate: false })
        : renderInlineItinerary(trip)
    ]);
    geojson = geojsonResult;
  } catch (error) {
    layoutRoot?.classList.remove("is-trip-loading");
    throw error;
  }

  if (enrichGeneration !== tripEnrichGeneration) {
    return;
  }

  const features = geojson.features || [];
  let lineFeatures = features
    .filter((feature) => {
      const type = feature?.geometry?.type;
      return type === "LineString" || type === "MultiLineString";
    })
    .map(normalizeLineFeature);
  lineFeatures = await resolveJourneyHikeLines(lineFeatures);
  lineFeatures = await resolveTransitLines(lineFeatures);
  lineFeatures = await resolveFerryLines(lineFeatures);
  const pointFeatures = features.filter((feature) => feature?.geometry?.type === "Point");

  clearTripLayers();
  createLineLayers(lineFeatures);
  createPointLayers(pointFeatures);
  applyFilters(fit);
  updateTripHeader(trip, features);
  renderStopsList(pointFeatures);
  renderHudJourneyStrip();
  setPanelCollapsed(false);
  layoutRoot?.classList.remove("is-trip-loading");
  requestAnimationFrame(updateLayoutInsets);

  void enrichTripLinesInBackground(lineFeatures, enrichGeneration);
}

function renderTripMenu() {
  if (!tripMenuGrid) {
    return;
  }

  const trips = getFilteredTrips();

  tripMenuGrid.innerHTML = trips
    .map((trip) => {
      const active = trip.key === state.selectedTrip;
      const budget =
        trip.budgetAudMin && trip.budgetAudMax
          ? `<span class="trip-card-budget">${formatAud(trip.budgetAudMin)}–${formatAud(trip.budgetAudMax).replace(/^AUD /, "")}</span>`
          : "";
      const distance = trip.distanceKm ? `<span class="trip-card-distance">${trip.distanceKm} km</span>` : "";
      const coverImg = trip.cover
        ? `<img class="trip-card-cover-img" src="${escapeHtml(trip.cover)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.parentElement?.classList.add('is-loaded')" onerror="this.remove()" />`
        : "";

      return `
        <button class="trip-card" type="button" data-trip-key="${trip.key}" data-active="${String(active)}">
          <div class="trip-card-cover">
            ${coverImg}
            <span class="trip-card-cover-fallback" aria-hidden="true"></span>
            <span class="trip-card-emoji">${trip.emoji || "🧭"}</span>
            ${trip.region ? `<span class="trip-card-region">${escapeHtml(trip.region)}</span>` : ""}
            <span class="trip-card-days">${trip.days} days</span>
          </div>
          <div class="trip-card-body">
            <h3>${escapeHtml(trip.title)}</h3>
            <p>${escapeHtml(trip.description)}</p>
            <div class="trip-card-meta">${distance}${budget}</div>
          </div>
        </button>
      `;
    })
    .join("");
}

function isJourneysMenuOpen() {
  return Boolean(tripOverlay?.classList.contains("open"));
}

function openTripOverlay() {
  if (!tripOverlay) {
    return;
  }

  if (_overlayHideTimeout) {
    clearTimeout(_overlayHideTimeout);
    _overlayHideTimeout = null;
  }

  renderContinentFilters();
  renderTripMenu();
  renderMintedJourneys();
  getFilteredTrips().slice(0, 3).forEach((trip) => prefetchTrip(trip.key));

  tripOverlay.classList.remove("hidden");
  void tripOverlay.offsetWidth;
  tripOverlay.classList.add("open");
  openJourneysMenuButton?.setAttribute("aria-expanded", "true");
  openJourneysMenuButton?.classList.add("is-open");
  closeTripMenuButton?.focus();
}

function closeTripOverlay() {
  if (!tripOverlay) {
    return;
  }

  const panel = tripOverlay.querySelector(".trip-overlay-panel");
  tripOverlay.classList.remove("open");

  if (panel) {
    const onEnd = (ev) => {
      if (ev.target === panel && !tripOverlay.classList.contains("open")) {
        tripOverlay.classList.add("hidden");
      }
    };
    panel.addEventListener("transitionend", onEnd, { once: true });
    _overlayHideTimeout = window.setTimeout(() => {
      if (!tripOverlay.classList.contains("open")) {
        tripOverlay.classList.add("hidden");
      }
      _overlayHideTimeout = null;
    }, 400);
  } else {
    tripOverlay.classList.add("hidden");
  }

  openJourneysMenuButton?.setAttribute("aria-expanded", "false");
  openJourneysMenuButton?.classList.remove("is-open");
  openJourneysMenuButton?.focus();
}

function handleJourneysMenuButtonClick() {
  if (hasActiveJourney()) {
    deselectJourney();
    return;
  }

  toggleJourneysMenu();
}

function toggleJourneysMenu() {
  if (isJourneysMenuOpen()) {
    closeTripOverlay();
  } else {
    openTripOverlay();
  }
}

function setupContinentFilters() {
  document.getElementById("continentFilters")?.addEventListener("click", (event) => {
    const chip = event.target.closest("button[data-continent]");
    if (!chip) {
      return;
    }

    state.continentFilter = chip.dataset.continent;
    renderContinentFilters();
    renderTripMenu();
  });
}

function setupTripOverlay() {
  if (openJourneysMenuButton) {
    openJourneysMenuButton.addEventListener("click", handleJourneysMenuButtonClick);
  }

  if (closeTripMenuButton) {
    closeTripMenuButton.addEventListener("click", closeTripOverlay);
  }

  if (tripOverlay) {
    tripOverlay.addEventListener("click", (event) => {
      if (event.target === tripOverlay) {
        closeTripOverlay();
      }
    });
    // Allow closing overlay with Escape key for accessibility
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && isJourneysMenuOpen()) {
        closeTripOverlay();
      }
    });
  }

  if (tripMenuGrid) {
    tripMenuGrid.addEventListener(
      "pointerenter",
      (event) => {
        const card = event.target.closest("button[data-trip-key]");
        if (card) {
          prefetchTrip(card.dataset.tripKey);
        }
      },
      true
    );

    tripMenuGrid.addEventListener("focusin", (event) => {
      const card = event.target.closest("button[data-trip-key]");
      if (card) {
        prefetchTrip(card.dataset.tripKey);
      }
    });

    tripMenuGrid.addEventListener("click", async (event) => {
      const card = event.target.closest("button[data-trip-key]");
      if (!card) {
        return;
      }

      const tripKey = card.dataset.tripKey;
      try {
        await loadTrip(tripKey, true);
        closeTripOverlay();
        renderTripMenu();
        setActiveView("map");
      } catch (error) {
        console.error(error);
        layoutRoot?.classList.remove("is-trip-loading");
        const content = document.getElementById("itineraryContent");
        content.innerHTML = "<p>There was an issue loading the selected trip.</p>";
      }
    });
  }
}

let panelCollapsed = false;

function setPanelCollapsed(collapsed) {
  const itineraryPanel = document.getElementById("itineraryPanel");
  const toggleButton = document.getElementById("togglePanel");
  const collapsePanelButton = document.getElementById("collapsePanelButton");
  const reopenButton = document.getElementById("reopenPanelButton");

  if (!itineraryPanel) {
    return;
  }

  panelCollapsed = collapsed;
  // On phones the panel never fully hides — it just toggles between peek and
  // expanded modes so the bottom sheet stays accessible above the bottom nav.
  if (typeof phoneMq === "function" && phoneMq()) {
    itineraryPanel.classList.remove("collapsed");
    itineraryPanel.classList.toggle("is-peek", collapsed);
    itineraryPanel.classList.toggle("is-expanded", !collapsed);
    panelCollapsed = false;
  } else {
    itineraryPanel.classList.remove("is-peek", "is-expanded");
    itineraryPanel.classList.toggle("collapsed", collapsed);
  }

  const journeyActive = hasActiveJourney();
  const label = collapsed ? "Show story" : "Hide story";
  const title = collapsed ? "Show the travel story panel" : "Hide the travel story panel";

  if (toggleButton) {
    toggleButton.hidden = collapsed || !journeyActive;
    toggleButton.setAttribute("aria-expanded", String(!collapsed));
    toggleButton.textContent = label;
    toggleButton.setAttribute("title", title);
  }

  if (collapsePanelButton) {
    collapsePanelButton.setAttribute("aria-expanded", String(!collapsed));
    collapsePanelButton.setAttribute("aria-label", collapsed ? "Open travel story panel" : "Close travel story panel");
  }

  if (reopenButton) {
    reopenButton.hidden = !collapsed || !journeyActive;
    reopenButton.setAttribute("aria-expanded", String(!collapsed));
  }

  syncStoryPanelLayout();
  syncMapPopupStacking();
  setTimeout(() => map.invalidateSize(), 260);
}

function updateLayoutInsets() {
  const stage = layoutRoot;
  const hud = document.querySelector(".map-hud");
  const panel = itineraryPanel;
  if (!stage) {
    return;
  }

  if (hud) {
    const stageRect = stage.getBoundingClientRect();
    const hudRect = hud.getBoundingClientRect();
    const hudBottom = Math.max(0, hudRect.bottom - stageRect.top);
    stage.style.setProperty("--layout-hud-bottom", `${Math.ceil(hudBottom + 8)}px`);
    stage.style.setProperty("--layout-hud-height", `${Math.ceil(hudRect.height)}px`);
  }

  const mapHintVisible = layoutRoot?.classList.contains("map-hint-visible") && mapHintBar && !mapHintBar.hidden;
  let mapHintOffset = 0;
  if (mapHintVisible) {
    const hintRect = mapHintBar.getBoundingClientRect();
    mapHintOffset = Math.ceil(hintRect.height + 12);
    stage.style.setProperty("--layout-map-hint", `${mapHintOffset}px`);
  } else {
    stage.style.setProperty("--layout-map-hint", "0px");
  }

  const narrow = window.innerWidth <= 980;
  const phone = window.innerWidth <= 640;
  let leafletBottom = 12 + mapHintOffset;

  if (phone) {
    // Phones: leaflet bottom controls sit above the bottom nav AND above the
    // (always-visible) bottom sheet so attribution stays readable.
    const navEl = document.getElementById("mobileBottomNav");
    const navHeight = navEl && !navEl.hidden ? Math.ceil(navEl.getBoundingClientRect().height) : 0;
    let panelOffset = 0;
    if (panel && !panel.classList.contains("collapsed")) {
      panelOffset = Math.ceil(panel.getBoundingClientRect().height + 8);
    }
    leafletBottom = navHeight + panelOffset;
  } else if (narrow) {
    if (!panelCollapsed && panel) {
      leafletBottom = Math.ceil(panel.getBoundingClientRect().height + 16);
    } else if (hud) {
      leafletBottom = Math.ceil(hud.getBoundingClientRect().height + 20);
    }
  } else if (!panelCollapsed) {
    leafletBottom = 16;
  }

  stage.style.setProperty("--leaflet-bottom-offset", `${leafletBottom}px`);
}

function syncStoryPanelLayout() {
  const open = !panelCollapsed;
  layoutRoot?.classList.toggle("story-panel-open", open);
  document.body.classList.toggle("story-panel-open", open);
  if (typeof updateMobileBottomNavActive === "function") {
    requestAnimationFrame(updateMobileBottomNavActive);
  }
  requestAnimationFrame(updateLayoutInsets);
}

function togglePanelCollapsed() {
  setPanelCollapsed(!panelCollapsed);
}

function setupPanelToggle() {
  const toggleButton = document.getElementById("togglePanel");
  const reopenButton = document.getElementById("reopenPanelButton");
  const collapsePanelButton = document.getElementById("collapsePanelButton");

  toggleButton?.addEventListener("click", togglePanelCollapsed);
  reopenButton?.addEventListener("click", () => setPanelCollapsed(false));
  collapsePanelButton?.addEventListener("click", togglePanelCollapsed);
}

function setupMobileUi() {
  const drawer = document.getElementById("mapControlsDrawer");
  const hint = document.getElementById("mapControlsHint");
  const mobileQuery = window.matchMedia("(max-width: 980px)");
  const phoneQuery = window.matchMedia("(max-width: 640px)");

  const hudNavEl = document.getElementById("hudNav");
  const hudNavHome = hudNavEl?.parentElement || null;
  const panelHeader = document.querySelector(".journey-panel-header");

  const controlsCard = drawer?.querySelector(".map-controls-card");
  const controlsHome = controlsCard?.parentElement || drawer || null;
  const mobileSheetBody = document.getElementById("mobileControlsBody");
  const moveHudNav = () => {
    if (!hudNavEl || !hudNavHome || !panelHeader) return;
    if (phoneQuery.matches) {
      if (hudNavEl.parentElement !== panelHeader) {
        const handleRow = panelHeader.querySelector(".panel-header-row");
        if (handleRow && handleRow.parentElement === panelHeader) {
          handleRow.insertAdjacentElement("afterend", hudNavEl);
        } else {
          panelHeader.insertBefore(hudNavEl, panelHeader.firstChild);
        }
      }
    } else if (hudNavEl.parentElement !== hudNavHome) {
      hudNavHome.appendChild(hudNavEl);
    }
    requestAnimationFrame(updateHudNavIndicator);
  };

  const moveControls = () => {
    if (!controlsCard) return;
    if (phoneQuery.matches) {
      // Move the entire controls card into the bottom sheet body so the
      // Layers tab in the bottom nav shows the same Basemap/Overlays/Explore/
      // Transport controls as the desktop drawer.
      if (mobileSheetBody && controlsCard.parentElement !== mobileSheetBody) {
        mobileSheetBody.appendChild(controlsCard);
      }
    } else if (controlsHome && controlsCard.parentElement !== controlsHome) {
      controlsHome.appendChild(controlsCard);
    }
  };

  const syncDrawer = () => {
    if (!drawer) {
      return;
    }
    if (mobileQuery.matches) {
      drawer.removeAttribute("open");
      if (hint) {
        hint.textContent = "Tap to expand";
      }
    } else {
      drawer.setAttribute("open", "");
      if (hint) {
        hint.textContent = "Layers & routes";
      }
    }
    requestAnimationFrame(updateLayoutInsets);
  };

  drawer?.addEventListener("toggle", () => {
    if (hint && mobileQuery.matches) {
      hint.textContent = drawer.open ? "Tap to collapse" : "Tap to expand";
    }
    requestAnimationFrame(updateLayoutInsets);
  });

  const handleQueryChange = () => {
    syncDrawer();
    moveHudNav();
    moveControls();
    syncMobilePanelMode();
  };

  if (typeof mobileQuery.addEventListener === "function") {
    mobileQuery.addEventListener("change", handleQueryChange);
    phoneQuery.addEventListener("change", handleQueryChange);
  } else {
    mobileQuery.addListener(handleQueryChange);
    phoneQuery.addListener(handleQueryChange);
  }

  handleQueryChange();
  setupMobileBottomNav();
  setupMobileSheet();
  setupMobilePanelGestures();
  setupMobileHudPill();
}

function setupMobileHudPill() {
  // On phones the top HUD becomes a slim pill that expands the bottom sheet
  // when tapped — gives the user a quick affordance to read the active
  // journey's full story without reaching the bottom nav.
  const brand = document.querySelector(".hud-brand");
  if (!brand || brand.dataset.mobileWired === "true") return;
  brand.dataset.mobileWired = "true";
  brand.addEventListener("click", (event) => {
    if (!phoneMq()) return;
    // Let inner interactive elements (e.g. nav buttons that haven't been
    // moved out yet) handle their own clicks.
    if (event.target.closest("button, a, input, .hud-nav-item")) return;
    setMobilePanelMode("expanded");
    setTimeout(updateMobileBottomNavActive, 60);
  });
}

// ----------------------------------------------------------------------------
// Phone bottom navigation + sheet + peek-mode bottom sheet
// ----------------------------------------------------------------------------

const phoneMq = () => window.matchMedia("(max-width: 640px)").matches;

function setMobilePanelMode(mode) {
  // mode: "peek" | "expanded" | "hidden"
  const panel = document.getElementById("itineraryPanel");
  if (!panel) return;
  panel.classList.remove("is-peek", "is-expanded");
  if (mode === "peek") panel.classList.add("is-peek");
  else if (mode === "expanded") panel.classList.add("is-expanded");
  requestAnimationFrame(updateLayoutInsets);
}

function syncMobilePanelMode() {
  const panel = document.getElementById("itineraryPanel");
  if (!panel) return;
  if (!phoneMq()) {
    panel.classList.remove("is-peek", "is-expanded");
    return;
  }
  // On phones we always keep the panel visible (no more `.collapsed`) — it
  // just toggles between peek and expanded.
  panel.classList.remove("collapsed");
  panelCollapsed = false;
  if (!panel.classList.contains("is-expanded") && !panel.classList.contains("is-peek")) {
    panel.classList.add("is-peek");
  }
  syncStoryPanelLayout();
  updateMobileBottomNavActive();
}

function updateMobileBottomNavActive() {
  const nav = document.getElementById("mobileBottomNav");
  if (!nav) return;
  const panel = document.getElementById("itineraryPanel");
  const exploreBtn = document.getElementById("exploreModeBtn");
  const isExpanded = panel?.classList.contains("is-expanded");
  const isExplore = exploreBtn?.getAttribute("aria-pressed") === "true";

  let active = "map";
  if (isExpanded) active = "story";
  else if (isExplore) active = "explore";

  nav.querySelectorAll("[data-nav]").forEach((btn) => {
    btn.dataset.active = btn.dataset.nav === active ? "true" : "false";
  });
}

function setupMobileBottomNav() {
  const nav = document.getElementById("mobileBottomNav");
  if (!nav || nav.dataset.wired === "true") return;
  nav.dataset.wired = "true";

  nav.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-nav]");
    if (!btn) return;
    const action = btn.dataset.nav;
    handleMobileNavAction(action);
  });
}

function handleMobileNavAction(action) {
  switch (action) {
    case "map": {
      // Collapse the bottom sheet to peek so the map is fully visible.
      setMobilePanelMode("peek");
      // Also close any open sheet/overlay so the user sees only the map.
      closeMobileControlsSheet();
      break;
    }
    case "explore": {
      document.getElementById("exploreModeBtn")?.click();
      break;
    }
    case "journeys": {
      document.getElementById("openJourneysMenuButton")?.click();
      break;
    }
    case "saved": {
      document.getElementById("openFavoritesButton")?.click();
      break;
    }
    case "layers": {
      openMobileControlsSheet();
      break;
    }
    case "story": {
      setMobilePanelMode("expanded");
      break;
    }
  }
  setTimeout(updateMobileBottomNavActive, 60);
}

function openMobileControlsSheet() {
  const sheet = document.getElementById("mobileControlsSheet");
  if (!sheet) return;
  sheet.hidden = false;
  void sheet.offsetWidth;
  sheet.classList.add("is-open");
}

function closeMobileControlsSheet() {
  const sheet = document.getElementById("mobileControlsSheet");
  if (!sheet) return;
  sheet.classList.remove("is-open");
  setTimeout(() => {
    if (!sheet.classList.contains("is-open")) sheet.hidden = true;
  }, 240);
}

function setupMobileSheet() {
  const sheet = document.getElementById("mobileControlsSheet");
  if (!sheet || sheet.dataset.wired === "true") return;
  sheet.dataset.wired = "true";
  sheet.addEventListener("click", (event) => {
    if (event.target.closest("[data-mobile-sheet-close]")) {
      closeMobileControlsSheet();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !sheet.hidden) closeMobileControlsSheet();
  });
}

function setupMobilePanelGestures() {
  const panel = document.getElementById("itineraryPanel");
  const header = panel?.querySelector(".journey-panel-header");
  if (!panel || !header || header.dataset.wired === "true") return;
  header.dataset.wired = "true";

  // Tap on the panel header (drag handle or title strip) toggles peek/expanded.
  header.addEventListener("click", (event) => {
    if (!phoneMq()) return;
    // Don't toggle if the user tapped a button inside the header.
    if (event.target.closest("button")) return;
    // Don't toggle if the user tapped a focused interactive (hud-nav item).
    if (event.target.closest(".hud-nav-item")) return;
    const isPeek = panel.classList.contains("is-peek");
    setMobilePanelMode(isPeek ? "expanded" : "peek");
    setTimeout(updateMobileBottomNavActive, 60);
  });

  // Drag-to-expand: vertical pointer drag — only when the user grabs the
  // slim handle strip at the top of the header. Anywhere else on the
  // header now scrolls/selects content normally.
  let dragState = null;
  header.addEventListener("pointerdown", (event) => {
    if (!phoneMq()) return;
    if (event.target.closest("button")) return;
    if (event.target.closest(".hud-nav-item")) return;
    if (!event.target.closest(".panel-header-row")) return;
    dragState = {
      startY: event.clientY,
      startHeight: panel.getBoundingClientRect().height,
      pointerId: event.pointerId,
      moved: false,
    };
    try { header.setPointerCapture(event.pointerId); } catch (_) {}
  });
  header.addEventListener("pointermove", (event) => {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const dy = dragState.startY - event.clientY;
    if (Math.abs(dy) > 6) dragState.moved = true;
  });
  header.addEventListener("pointerup", (event) => {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    const dy = dragState.startY - event.clientY;
    if (dragState.moved) {
      // Swipe up: expand; swipe down: peek.
      if (dy > 30) setMobilePanelMode("expanded");
      else if (dy < -30) setMobilePanelMode("peek");
      setTimeout(updateMobileBottomNavActive, 60);
    }
    dragState = null;
  });
  header.addEventListener("pointercancel", () => {
    dragState = null;
  });
}

async function initializeTrips() {
  const placeDetailsResponse = await fetch("./Trip/place-details.json");
  if (placeDetailsResponse.ok) {
    placeDetails = await placeDetailsResponse.json();
  }

  await Promise.all([
    initCityCatalog(),
    initHikeCatalog(),
    initParkCatalog(),
    initPoiCatalog(),
  ]);

  const response = await fetch("./Trip/journeys.json");
  if (!response.ok) {
    throw new Error("Could not load journey manifest.");
  }

  const manifest = await response.json();
  state.trips = manifest.trips || [];
  updateJourneysMenuHint();

  state.selectedTrip = null;
  renderEmptyJourneyPanel();
  renderContinentFilters();
  renderTripMenu();
  renderHudJourneyStrip();
  setPanelCollapsed(true);
  syncStoryPanelLayout();
  showWelcomeOverlay();
  requestAnimationFrame(updateHudNavIndicator);
}

function setupWelcomeAndExplore() {
  document.getElementById("welcomeExploreBtn")?.addEventListener("click", () => {
    enterExploreMode({ dismissWelcome: true });
  });

  document.getElementById("welcomeJourneysBtn")?.addEventListener("click", () => {
    dismissWelcomeOverlay();
    openTripOverlay();
  });

  welcomeOverlay?.querySelectorAll("[data-welcome-dismiss]").forEach((el) => {
    el.addEventListener("click", dismissWelcomeOverlay);
  });

  document.getElementById("emptyStateExploreBtn")?.addEventListener("click", () => {
    enterExploreMode({ dismissWelcome: true });
  });

  document.getElementById("emptyStateJourneysBtn")?.addEventListener("click", () => {
    dismissWelcomeOverlay();
    openTripOverlay();
  });

  exploreModeBtn?.addEventListener("click", () => {
    if (state.exploreCities || state.exploreParks || state.exploreHikes || state.explorePoi) {
      if (state.exploreCities) {
        setExploreCities(false);
      }
      if (state.exploreParks) {
        setExploreParks(false);
      }
      if (state.exploreHikes) {
        setExploreHikes(false);
      }
      if (state.explorePoi) {
        setExplorePoi(false);
      }
      hideMapExploreHint();
      updateHudJourneyState();
      syncExploreHudButton();
      return;
    }
    enterExploreMode({ dismissWelcome: true, flyToEurope: !hasActiveJourney() });
  });

  setupMapHintBar();

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && welcomeOverlay?.classList.contains("open")) {
      dismissWelcomeOverlay();
      return;
    }
    if (
      ev.key === "Escape" &&
      mapHintBar &&
      !mapHintBar.hidden &&
      layoutRoot?.classList.contains("map-hint-visible")
    ) {
      hideMapExploreHint();
    }
  });
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    return;
  }
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js", { scope: "/", updateViaCache: "none" })
      .then((registration) => {
        registration.update().catch(() => {});
        if (registration.waiting) {
          registration.waiting.postMessage("skip-waiting");
        }
        registration.addEventListener("updatefound", () => {
          const installing = registration.installing;
          if (!installing) return;
          installing.addEventListener("statechange", () => {
            if (installing.state === "installed" && navigator.serviceWorker.controller) {
              installing.postMessage("skip-waiting");
            }
          });
        });
      })
      .catch((err) => console.warn("[sw] registration failed", err));

    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloaded || !navigator.serviceWorker.controller) return;
      reloaded = true;
      window.location.reload();
    });
  });
}

async function maybeOpenSharedJourneyFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("journey");
  if (!code) {
    return;
  }
  try {
    await openSharedJourney(code);
  } catch (err) {
    console.warn("[shared journey]", err);
  }
}

async function openSharedJourney(code) {
  const journey = await fetchSharedJourney(code);
  const geojsonUrl = `/api/journeys/code/${encodeURIComponent(code.toUpperCase())}/geojson`;
  const tripKey = `shared-${journey.code}`;
  const tripEntry = {
    key: tripKey,
    emoji: journey.emoji || "🧭",
    continent: journey.continent || "europe",
    title: journey.title,
    description: journey.description || "",
    geojson: geojsonUrl,
    days: journey.days || journey.stops?.length || 1,
    distanceKm: journey.distanceKm || 0,
    region: journey.region || "",
    highlights: journey.highlights || [],
    cover: journey.cover || journey.stops?.[0]?.photo || "",
    sharedCode: journey.code,
    author: journey.author || ""
  };
  const existing = state.trips.findIndex((trip) => trip.key === tripKey);
  if (existing >= 0) {
    state.trips[existing] = tripEntry;
  } else {
    state.trips = [tripEntry, ...state.trips];
  }
  closeTripOverlay();
  dismissWelcomeOverlay();
  try {
    await loadTrip(tripKey, true);
    setActiveView("map");
  } catch (err) {
    console.error("[shared journey] load failed", err);
    throw err;
  }
}

// ----------------------------------------------------------------------------
// Season strip — click-to-pin / hover-to-peek
// ----------------------------------------------------------------------------

function setSeasonCellAnchor(cell) {
  // Re-anchor the tooltip based on the cell's actual screen position so a
  // month near the viewport edge doesn't clip its popover off-screen.
  if (!cell) return;
  const rect = cell.getBoundingClientRect();
  const vw = window.innerWidth || document.documentElement.clientWidth || 0;
  const margin = 80;
  if (rect.left < margin) {
    cell.dataset.anchor = "start";
  } else if (rect.right > vw - margin) {
    cell.dataset.anchor = "end";
  } else {
    cell.dataset.anchor = "center";
  }
}

function setupSeasonStripInteractions() {
  document.addEventListener("click", (event) => {
    const cell = event.target.closest("[data-season-cell]");
    if (cell) {
      event.preventDefault();
      const strip = cell.closest("[data-season-strip]");
      if (!strip) return;
      const wasActive = cell.classList.contains("is-active");
      strip.querySelectorAll(".season-strip__cell.is-active").forEach((c) => {
        c.classList.remove("is-active");
      });
      if (!wasActive) {
        setSeasonCellAnchor(cell);
        cell.classList.add("is-active");
      }
      return;
    }
    document.querySelectorAll(".season-strip__cell.is-active").forEach((c) => {
      c.classList.remove("is-active");
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const active = document.querySelector(".season-strip__cell.is-active");
    if (active) {
      active.classList.remove("is-active");
    }
  });

  // Re-anchor hovered cell on pointerover (desktop only triggers :hover here).
  document.addEventListener("pointerover", (event) => {
    const cell = event.target?.closest?.("[data-season-cell]");
    if (cell) setSeasonCellAnchor(cell);
  });

  window.addEventListener("resize", () => {
    document.querySelectorAll(".season-strip__cell.is-active").forEach(setSeasonCellAnchor);
  });
}

// ----------------------------------------------------------------------------
// Favorites (hearted places)
// ----------------------------------------------------------------------------

const favoritesOverlayState = { kind: "all" };

function setupFavoritesUi() {
  document.body.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-favorite-btn]");
    if (!btn) return;
    const entry = btn._favEntry;
    if (!entry) return;
    event.preventDefault();
    event.stopPropagation();
    toggleFavorite(entry);
    refreshFavoriteButton(btn);
  });

  document.getElementById("openFavoritesButton")?.addEventListener("click", openFavoritesOverlay);

  const overlay = document.getElementById("favoritesOverlay");
  overlay?.querySelectorAll("[data-favorites-close]").forEach((el) => {
    el.addEventListener("click", closeFavoritesOverlay);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && overlay && !overlay.hidden) {
      closeFavoritesOverlay();
    }
  });

  document.getElementById("favoritesOverlayFilter")?.addEventListener("click", (event) => {
    const chip = event.target.closest("button[data-fav-filter]");
    if (!chip) return;
    favoritesOverlayState.kind = chip.dataset.favFilter;
    renderFavoritesOverlay();
  });

  document.getElementById("favoritesOverlayGrid")?.addEventListener("click", (event) => {
    const removeBtn = event.target.closest("[data-fav-overlay-remove]");
    const openBtn = event.target.closest("[data-fav-overlay-open]");
    const addBtn = event.target.closest("[data-fav-overlay-add]");
    const id = event.target.closest("[data-fav-id]")?.dataset.favId;
    const kind = event.target.closest("[data-fav-id]")?.dataset.favKind;
    const fav = id && kind ? getFavorites().find((f) => f.id === id && f.kind === kind) : null;
    if (!fav) return;
    if (removeBtn) {
      toggleFavorite(fav);
    } else if (addBtn) {
      const already = builderState.stops.some(
        (stop) => stop.id === fav.id && stop.kind === fav.kind
      );
      if (already) return;
      addBuilderStop({
        id: fav.id,
        kind: fav.kind,
        name: fav.name,
        country: fav.country,
        tagline: fav.tagline,
        lat: fav.lat,
        lng: fav.lng,
      });
      const card = addBtn.closest(".favorites-overlay__card");
      if (card) card.classList.add("is-added");
      addBtn.disabled = true;
      addBtn.textContent = "Added";
      renderBuilderFavorites();
    } else if (openBtn) {
      closeFavoritesOverlay();
      void openFavoriteAsDetail(fav);
    }
  });

  document.getElementById("favoritesClearBtn")?.addEventListener("click", () => {
    const favs = filteredFavorites();
    if (!favs.length) return;
    if (
      !window.confirm(
        favoritesOverlayState.kind === "all"
          ? `Remove all ${favs.length} favorites?`
          : `Remove ${favs.length} ${favoritesOverlayState.kind} favorites?`
      )
    ) {
      return;
    }
    favs.forEach((fav) => toggleFavorite(fav));
    renderFavoritesOverlay();
  });

  subscribeFavorites(() => {
    document
      .querySelectorAll("[data-favorite-btn]")
      .forEach((btn) => refreshFavoriteButton(btn));
    renderBuilderFavorites();
    renderFavoritesOverlay();
    updateFavoritesHudHint();
  });

  renderBuilderFavorites();
  renderFavoritesOverlay();
  updateFavoritesHudHint();
}

function updateFavoritesHudHint() {
  const hint = document.getElementById("favoritesMenuHint");
  if (!hint) return;
  const count = getFavorites().length;
  hint.textContent = count === 0 ? "Nothing saved" : `${count} saved`;
}

function filteredFavorites() {
  const all = getFavorites();
  if (favoritesOverlayState.kind === "all") {
    return all;
  }
  return all.filter((fav) => fav.kind === favoritesOverlayState.kind);
}

function openFavoritesOverlay() {
  const overlay = document.getElementById("favoritesOverlay");
  if (!overlay) return;
  overlay.hidden = false;
  void overlay.offsetWidth;
  overlay.classList.add("is-open");
  renderFavoritesOverlay();
  document.getElementById("openFavoritesButton")?.setAttribute("aria-expanded", "true");
}

function closeFavoritesOverlay() {
  const overlay = document.getElementById("favoritesOverlay");
  if (!overlay) return;
  overlay.classList.remove("is-open");
  document.getElementById("openFavoritesButton")?.setAttribute("aria-expanded", "false");
  window.setTimeout(() => {
    if (!overlay.classList.contains("is-open")) {
      overlay.hidden = true;
    }
  }, 240);
}

const FAV_FLY_ZOOM = {
  city: 12,
  poi: 12,
  park: 10,
  hike: 11,
};

function flyToFavorite(fav) {
  if (!map || !fav || !Number.isFinite(fav.lat) || !Number.isFinite(fav.lng)) return;
  const targetZoom = FAV_FLY_ZOOM[fav.kind] || 11;
  const zoom = Math.max(map.getZoom(), targetZoom);
  map.flyTo([fav.lat, fav.lng], zoom, { duration: 0.85 });
}

async function openFavoriteAsDetail(fav) {
  try {
    flyToFavorite(fav);
    if (fav.kind === "city") {
      const details = await fetchCityById(fav.id, { name: fav.name, country: fav.country });
      await openPlaceStory(details?.name || fav.name, details || { name: fav.name });
    } else if (fav.kind === "park") {
      const details = await fetchParkById(fav.id);
      await openPlaceStory(details?.name || fav.name, details || { name: fav.name, kind: "park" });
    } else if (fav.kind === "poi") {
      const details = await fetchPoiById(fav.id);
      await openPlaceStory(details?.name || fav.name, details || { name: fav.name, kind: "poi" });
    } else if (fav.kind === "hike") {
      const details = await fetchHikeById(fav.id);
      if (details) {
        await showActiveHikeRoute(details);
        openHikeStory(details, details);
      }
    }
  } catch (err) {
    console.warn("openFavoriteAsDetail failed", err);
  }
}

function renderFavoritesOverlay() {
  const overlay = document.getElementById("favoritesOverlay");
  if (!overlay) return;

  const grid = document.getElementById("favoritesOverlayGrid");
  const empty = document.getElementById("favoritesOverlayEmpty");
  const count = document.getElementById("favoritesOverlayCount");
  const filter = document.getElementById("favoritesOverlayFilter");
  const clear = document.getElementById("favoritesClearBtn");

  const all = getFavorites();
  if (!all.length) {
    favoritesOverlayState.kind = "all";
    if (grid) grid.innerHTML = "";
    if (filter) filter.hidden = true;
    if (empty) empty.hidden = false;
    if (count) count.textContent = "No favorites yet — tap a heart on any card to save it.";
    if (clear) clear.disabled = true;
    return;
  }

  if (empty) empty.hidden = true;

  const kindCounts = all.reduce(
    (acc, fav) => {
      acc[fav.kind] = (acc[fav.kind] || 0) + 1;
      return acc;
    },
    { city: 0, park: 0, hike: 0, poi: 0 }
  );

  if (
    favoritesOverlayState.kind !== "all" &&
    (kindCounts[favoritesOverlayState.kind] || 0) === 0
  ) {
    favoritesOverlayState.kind = "all";
  }

  if (filter) {
    filter.hidden = false;
    const chips = [
      { id: "all", label: "All", n: all.length },
      { id: "city", label: "Cities", n: kindCounts.city },
      { id: "park", label: "Parks", n: kindCounts.park },
      { id: "hike", label: "Trails", n: kindCounts.hike },
      { id: "poi", label: "Landmarks", n: kindCounts.poi },
    ];
    filter.innerHTML = chips
      .map((chip) => {
        const active = favoritesOverlayState.kind === chip.id;
        return `
          <button type="button" class="favorites-overlay__chip${active ? " is-active" : ""}"
                  data-fav-filter="${chip.id}" ${chip.n === 0 ? "disabled" : ""}
                  aria-pressed="${active ? "true" : "false"}">
            ${escapeHtml(chip.label)}<span>${chip.n}</span>
          </button>
        `;
      })
      .join("");
  }

  const list = filteredFavorites();
  if (count) {
    const nouns = {
      all: ["place", "places"],
      city: ["city", "cities"],
      park: ["park", "parks"],
      hike: ["trail", "trails"],
      poi: ["landmark", "landmarks"],
    };
    const [singular, plural] = nouns[favoritesOverlayState.kind] || nouns.all;
    count.textContent = `${list.length} ${list.length === 1 ? singular : plural} saved`;
  }

  if (clear) clear.disabled = list.length === 0;

  if (!grid) return;
  if (!list.length) {
    grid.innerHTML = `<p class="favorites-overlay__empty">Nothing in this category yet.</p>`;
    return;
  }

  grid.innerHTML = list
    .map((fav) => {
      const icon = KIND_EMOJI[fav.kind] || "📍";
      const meta = [fav.country, fav.kind].filter(Boolean).join(" · ") || "Saved";
      const photoStyle = fav.photo
        ? ` style="background-image:url('${fav.photo.replace(/'/g, "%27")}')"`
        : "";
      const inJourney = builderState.stops.some(
        (stop) => stop.id === fav.id && stop.kind === fav.kind
      );
      return `
        <article class="favorites-overlay__card${inJourney ? " is-added" : ""}"
                 data-fav-id="${escapeAttr(fav.id)}" data-fav-kind="${escapeAttr(fav.kind)}">
          <button type="button" class="favorites-overlay__cover" data-fav-overlay-open${photoStyle}>
            ${fav.photo ? "" : `<span class="favorites-overlay__cover-icon" aria-hidden="true">${icon}</span>`}
          </button>
          <div class="favorites-overlay__body">
            <button type="button" class="favorites-overlay__name" data-fav-overlay-open>${escapeHtml(fav.name)}</button>
            <p class="favorites-overlay__meta">${escapeHtml(meta)}</p>
            ${fav.tagline ? `<p class="favorites-overlay__tag">${escapeHtml(fav.tagline)}</p>` : ""}
          </div>
          <div class="favorites-overlay__card-actions">
            <button type="button" class="trip-overlay-action trip-overlay-action--primary" data-fav-overlay-add ${inJourney ? "disabled" : ""}>
              ${inJourney ? "Added" : "+ Journey"}
            </button>
            <button type="button" class="trip-overlay-action" data-fav-overlay-remove>Remove</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function favoriteEntryFromDetails(details, fallback = {}) {
  if (!details && !fallback) return null;
  const merged = { ...fallback, ...(details || {}) };
  const kind = merged.kind || fallback.kind || "stop";
  const id = merged.id || fallback.id;
  const lat = Number(merged.lat ?? fallback.lat);
  const lng = Number(merged.lng ?? fallback.lng);
  if (!id || !Number.isFinite(lat) || !Number.isFinite(lng)) {
    return null;
  }
  const photo =
    merged.photo ||
    merged.cover ||
    (Array.isArray(merged.photos) ? merged.photos[0]?.url : "") ||
    "";
  return {
    id,
    kind,
    name: merged.name || fallback.name || "Saved place",
    country: merged.country || fallback.country || "",
    lat,
    lng,
    photo,
    tagline: merged.tagline || merged.summary || "",
  };
}

function bindFavoriteButton(buttonId, entry) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  if (!entry) {
    btn.hidden = true;
    btn._favEntry = null;
    return;
  }
  btn.hidden = false;
  btn._favEntry = entry;
  refreshFavoriteButton(btn);
}

function refreshFavoriteButton(btn) {
  if (!btn) return;
  const entry = btn._favEntry;
  if (!entry) return;
  const active = isFavorite(entry.kind, entry.id);
  btn.classList.toggle("is-active", active);
  btn.setAttribute("aria-pressed", active ? "true" : "false");
  btn.setAttribute(
    "aria-label",
    active ? `Remove ${entry.name} from favorites` : `Save ${entry.name} to favorites`
  );
}

// ----------------------------------------------------------------------------
// Country dossier
// ----------------------------------------------------------------------------

let dossierLastBounds = null;

function setupCountryDossier() {
  const overlay = document.getElementById("countryDossier");
  if (!overlay) return;

  overlay.querySelectorAll("[data-country-close]").forEach((el) => {
    el.addEventListener("click", closeCountryDossier);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && overlay.classList.contains("is-open")) {
      closeCountryDossier();
    }
  });

  document.getElementById("countryDossierExplore")?.addEventListener("click", () => {
    if (!dossierLastBounds) {
      return;
    }
    closeCountryDossier();
    if (!state.exploreCities) {
      setExploreCities(true);
    }
    const { west, south, east, north } = dossierLastBounds;
    map.fitBounds(
      [
        [south, west],
        [north, east]
      ],
      { padding: [48, 48], maxZoom: 8 }
    );
  });

  document.getElementById("countryDossierBuild")?.addEventListener("click", () => {
    closeCountryDossier();
    openJourneyBuilder();
  });

  overlay.addEventListener("click", (event) => {
    const card = event.target.closest("[data-dossier-card]");
    if (!card) return;
    const kind = card.dataset.kind;
    const id = card.dataset.id;
    const name = card.dataset.name;
    closeCountryDossier();
    void openDossierCardAsDetail({ kind, id, name });
  });
}

async function openDossierCardAsDetail({ kind, id, name }) {
  try {
    if (kind === "city") {
      const details = await fetchCityById(id, { name });
      await openPlaceStory(details.name || name, details);
    } else if (kind === "park") {
      const details = await fetchParkById(id);
      await openPlaceStory(details.name || name, details);
    } else if (kind === "poi") {
      const details = await fetchPoiById(id);
      await openPlaceStory(details.name || name, details);
    } else if (kind === "hike") {
      const details = await fetchHikeById(id);
      await showActiveHikeRoute(details);
      openHikeStory(details, details);
    }
  } catch (err) {
    console.warn("dossier card open failed", err);
  }
}

function countryDossierCardHtml(item) {
  const country = item.country || "";
  const meta = (() => {
    if (item.kind === "park") {
      const bio = item.biodiversity ? `Biodiversity ${item.biodiversity}/5` : "";
      return [bio, item.stay].filter(Boolean).join(" · ");
    }
    if (item.kind === "hike") {
      return formatHikeLength(item.length_km) || "Trail";
    }
    if (item.kind === "poi") {
      return poiCategoryLabel(item.category);
    }
    if (item.pop && Number(item.pop) > 0) {
      const pop = Number(item.pop);
      return pop >= 1_000_000
        ? `${(pop / 1_000_000).toFixed(1)}M people`
        : `${Math.round(pop / 1000)}k people`;
    }
    return country;
  })();
  const photoUrl = item.photo ? escapeAttr(item.photo) : "";
  const style = photoUrl ? `style="background-image:url('${photoUrl}')"` : "";
  return `
    <button class="country-dossier__card" type="button"
            data-dossier-card data-kind="${item.kind}" data-id="${escapeAttr(item.id)}" data-name="${escapeAttr(item.name)}">
      <span class="country-dossier__card-cover" ${style}></span>
      <span class="country-dossier__card-text">
        <span class="country-dossier__card-name">${escapeHtml(item.name)}</span>
        <span class="country-dossier__card-meta">${escapeHtml(meta || "")}</span>
      </span>
    </button>
  `;
}

function fillDossierSection(sectionId, items) {
  const section = document.getElementById(sectionId);
  if (!section) return;
  const target = section.querySelector(".country-dossier__cards");
  if (!target) return;
  if (!items || !items.length) {
    section.hidden = true;
    target.innerHTML = "";
    return;
  }
  section.hidden = false;
  target.innerHTML = items.map(countryDossierCardHtml).join("");
}

async function openCountryDossier({ cc, country, bounds }) {
  const code = (cc || "").toLowerCase();
  if (!code) return;
  const overlay = document.getElementById("countryDossier");
  if (!overlay) return;

  await loadSeasonHints();
  let dossier;
  try {
    dossier = await fetchCountryDossier(code);
  } catch (err) {
    console.warn("Country dossier fetch failed:", err);
    dossier = {
      cc: code,
      country: country || code.toUpperCase(),
      bounds: bounds || null,
      counts: { cities: 0, parks: 0, hikes: 0, pois: 0 },
      highlights: { cities: [], parks: [], hikes: [], pois: [] },
      season: null,
    };
  }

  dossierLastBounds = dossier.bounds || bounds || null;

  overlay.hidden = false;
  void overlay.offsetWidth;
  overlay.classList.add("is-open");
  setDetailOverlayClass("country-dossier-open", true);

  const titleEl = document.getElementById("countryDossierTitle");
  const leadEl = document.getElementById("countryDossierLead");
  const flagEl = document.getElementById("countryDossierFlag");
  const flagNameEl = document.getElementById("countryDossierFlagName");
  const heroBg = document.getElementById("countryDossierHeroBg");
  if (titleEl) titleEl.textContent = dossier.country || country || code.toUpperCase();
  if (leadEl) {
    leadEl.textContent = dossier.season?.note || dossier.season?.best
      ? `Best window: ${dossier.season?.best || "year-round"}`
      : "Cities, parks, trails and landmarks at a glance.";
  }
  const flagUrl = countryFlagUrl(dossier.country || country);
  if (flagEl) {
    if (flagUrl) {
      flagEl.hidden = false;
      flagEl.src = flagUrl;
      flagEl.alt = `Flag of ${dossier.country || country || ""}`;
    } else {
      flagEl.hidden = true;
      flagEl.removeAttribute("src");
    }
  }
  if (flagNameEl) {
    flagNameEl.textContent = dossier.country || country || code.toUpperCase();
  }
  const heroPhoto =
    dossier.highlights?.cities?.find((c) => c.photo)?.photo ||
    dossier.highlights?.parks?.find((p) => p.photo)?.photo ||
    dossier.highlights?.pois?.find((p) => p.photo)?.photo ||
    dossier.highlights?.hikes?.find((h) => h.photo)?.photo ||
    "";
  if (heroBg) {
    heroBg.style.backgroundImage = heroPhoto ? `url('${heroPhoto.replace(/'/g, "%27")}')` : "";
  }

  const countsEl = document.getElementById("countryDossierCounts");
  if (countsEl) {
    const c = dossier.counts || {};
    countsEl.innerHTML = `
      <div><span>${(c.cities || 0).toLocaleString()}</span> cities</div>
      <div><span>${(c.parks || 0).toLocaleString()}</span> parks</div>
      <div><span>${(c.hikes || 0).toLocaleString()}</span> trails</div>
      <div><span>${(c.pois || 0).toLocaleString()}</span> landmarks</div>
    `;
  }

  fillDossierSection("countryDossierCities", dossier.highlights?.cities);
  fillDossierSection("countryDossierParks", dossier.highlights?.parks);
  fillDossierSection("countryDossierHikes", dossier.highlights?.hikes);
  fillDossierSection("countryDossierPois", dossier.highlights?.pois);

  const seasonHost = document.getElementById("countryDossierSeason");
  if (seasonHost) {
    seasonHost.innerHTML = buildTimeOfYearHtml(dossier.country || country || "");
  }
  requestAnimationFrame(updateLayoutInsets);
}

function closeCountryDossier() {
  const overlay = document.getElementById("countryDossier");
  if (!overlay) return;
  overlay.classList.remove("is-open");
  setDetailOverlayClass("country-dossier-open", false);
  window.setTimeout(() => {
    if (!overlay.classList.contains("is-open")) {
      overlay.hidden = true;
    }
  }, 280);
}

// ----------------------------------------------------------------------------
// Journey builder + share codes
// ----------------------------------------------------------------------------

const builderState = {
  stops: [],
  searchToken: 0,
  pickMode: false,
  addMode: "search",
  reopenAfterStory: false,
};

const KIND_EMOJI = {
  city: "🏙️",
  park: "🌲",
  hike: "🥾",
  poi: "🏛️",
  stop: "📍",
  custom: "📌",
};

const MODE_EMOJI = {
  drive: "🚗",
  train: "🚂",
  ferry: "⛴️",
  fly: "✈️",
  hike: "🥾",
};

function setupJourneyBuilder() {
  const overlay = document.getElementById("journeyBuilder");
  if (!overlay) return;

  overlay.querySelectorAll("[data-builder-close]").forEach((el) => {
    el.addEventListener("click", () => closeJourneyBuilder());
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && overlay.classList.contains("is-open")) {
      closeJourneyBuilder();
    }
  });

  document.getElementById("openJourneyBuilderBtn")?.addEventListener("click", () => {
    closeTripOverlay();
    openJourneyBuilder();
  });

  document.getElementById("builderResumeFab")?.addEventListener("click", () => {
    openJourneyBuilder();
  });

  document.getElementById("builderFavoritesList")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-fav-add]");
    if (!btn || btn.disabled) return;
    const id = btn.dataset.favId;
    const kind = btn.dataset.favKind;
    const fav = getFavorites().find((entry) => entry.id === id && entry.kind === kind);
    if (!fav) return;
    addBuilderStop({
      id: fav.id,
      kind: fav.kind,
      name: fav.name,
      country: fav.country,
      tagline: fav.tagline,
      lat: fav.lat,
      lng: fav.lng,
    });
    renderBuilderFavorites();
  });

  document.getElementById("journeyCodeForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("journeyCodeInput");
    const errEl = document.getElementById("journeyCodeError");
    const raw = (input?.value || "").trim().toUpperCase().replace(/[^A-Z2-9]/g, "");
    if (errEl) {
      errEl.hidden = true;
      errEl.textContent = "";
    }
    if (!isJourneyCode(raw)) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = "Codes are 4–12 alphanumeric characters.";
      }
      return;
    }
    try {
      await openSharedJourney(raw);
      if (input) input.value = "";
    } catch (err) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = "We couldn't find that journey code.";
      }
    }
  });

  document.getElementById("builderModeSearch")?.addEventListener("click", () => setBuilderAddMode("search"));
  document.getElementById("builderModeMap")?.addEventListener("click", () => setBuilderAddMode("map"));
  document.getElementById("builderModeFavorites")?.addEventListener("click", () => setBuilderAddMode("favorites"));
  document.getElementById("builderPickOnMap")?.addEventListener("click", () => activateBuilderPickMode());
  document.getElementById("builderPickCancel")?.addEventListener("click", () => deactivateBuilderPickMode({ reopen: true }));

  const search = document.getElementById("builderSearchInput");
  const clear = document.getElementById("builderSearchClear");
  const resultsEl = document.getElementById("builderSearchResults");
  search?.addEventListener("input", () => {
    if (clear) clear.hidden = !search.value.trim().length;
    void runBuilderSearch(search.value);
  });
  clear?.addEventListener("click", () => {
    if (search) search.value = "";
    if (clear) clear.hidden = true;
    if (resultsEl) {
      resultsEl.hidden = true;
      resultsEl.innerHTML = "";
    }
  });
  resultsEl?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-builder-add]");
    if (!button) return;
    const data = JSON.parse(button.dataset.payload || "{}");
    addBuilderStop(data);
    if (search) search.value = "";
    if (clear) clear.hidden = true;
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    search?.focus();
  });

  document.getElementById("builderStops")?.addEventListener("click", (event) => {
    const removeBtn = event.target.closest("[data-stop-remove]");
    const upBtn = event.target.closest("[data-stop-up]");
    const downBtn = event.target.closest("[data-stop-down]");
    const focusBtn = event.target.closest("[data-stop-focus]");
    if (focusBtn) {
      const index = Number(focusBtn.dataset.stopFocus);
      const stop = builderState.stops[index];
      if (stop) {
        void focusBuilderStop(stop);
      }
      return;
    }
    if (removeBtn) {
      const index = Number(removeBtn.dataset.stopRemove);
      builderState.stops.splice(index, 1);
      renderBuilderStops();
    } else if (upBtn) {
      const index = Number(upBtn.dataset.stopUp);
      if (index > 0) {
        [builderState.stops[index - 1], builderState.stops[index]] = [
          builderState.stops[index],
          builderState.stops[index - 1],
        ];
        renderBuilderStops();
      }
    } else if (downBtn) {
      const index = Number(downBtn.dataset.stopDown);
      if (index < builderState.stops.length - 1) {
        [builderState.stops[index + 1], builderState.stops[index]] = [
          builderState.stops[index],
          builderState.stops[index + 1],
        ];
        renderBuilderStops();
      }
    }
  });

  document.getElementById("builderStops")?.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-stop-mode]");
    if (!select) return;
    const index = Number(select.dataset.stopMode);
    if (builderState.stops[index]) {
      builderState.stops[index].mode = select.value;
      renderBuilderStops();
    }
  });

  document.getElementById("builderReset")?.addEventListener("click", () => {
    builderState.stops = [];
    ["builderTitle", "builderDescription", "builderRegion", "builderAuthor"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });
    const daysEl = document.getElementById("builderDays");
    if (daysEl) daysEl.value = "7";
    renderBuilderStops();
    const result = document.getElementById("builderResult");
    if (result) result.hidden = true;
    clearJourneyDraft();
  });

  document.getElementById("builderMint")?.addEventListener("click", () => {
    void mintBuilderJourney();
  });

  ["builderTitle", "builderDescription", "builderRegion", "builderAuthor", "builderDays"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("input", scheduleSaveBuilderDraft);
      el.addEventListener("change", scheduleSaveBuilderDraft);
    }
  );

  restoreBuilderDraft();

  document.getElementById("builderResultCopy")?.addEventListener("click", () => {
    const link = document.getElementById("builderResultLink");
    if (!link) return;
    link.select();
    try {
      navigator.clipboard.writeText(link.value);
    } catch {
      document.execCommand("copy");
    }
  });

  document.getElementById("builderResultOpen")?.addEventListener("click", () => {
    const code = document.getElementById("builderResultCode")?.textContent?.trim();
    if (!code) return;
    closeJourneyBuilder();
    void openSharedJourney(code);
  });
}

function openJourneyBuilder() {
  const overlay = document.getElementById("journeyBuilder");
  if (!overlay) return;
  overlay.hidden = false;
  void overlay.offsetWidth;
  overlay.classList.add("is-open");
  setDetailOverlayClass("journey-builder-open", true);
  renderBuilderStops();
  renderBuilderFavorites();
  updateBuilderFab();
  requestAnimationFrame(updateLayoutInsets);
}

function renderBuilderFavorites() {
  const list = document.getElementById("builderFavoritesList");
  const empty = document.getElementById("builderFavoritesEmpty");
  const badge = document.getElementById("builderFavoritesBadge");
  const favs = getFavorites();

  if (badge) {
    if (favs.length) {
      badge.hidden = false;
      badge.textContent = String(favs.length);
    } else {
      badge.hidden = true;
    }
  }

  if (!list) return;

  if (!favs.length) {
    list.innerHTML = "";
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;

  list.innerHTML = favs
    .map((fav) => {
      const inJourney = builderState.stops.some(
        (stop) => stop.id === fav.id && stop.kind === fav.kind
      );
      const icon = KIND_EMOJI[fav.kind] || "📍";
      const meta = [fav.country, fav.kind].filter(Boolean).join(" · ");
      const photoStyle = fav.photo
        ? ` style="background-image:url('${fav.photo.replace(/'/g, "%27")}')"`
        : "";
      return `
        <button type="button"
                class="journey-builder__fav-row${inJourney ? " is-added" : ""}"
                data-fav-add data-fav-id="${escapeAttr(fav.id)}" data-fav-kind="${escapeAttr(fav.kind)}"
                ${inJourney ? "disabled" : ""}
                aria-label="${inJourney ? `${escapeAttr(fav.name)} is already in your journey` : `Add ${escapeAttr(fav.name)} to journey`}">
          <span class="journey-builder__fav-cover"${photoStyle}>
            ${fav.photo ? "" : `<span class="journey-builder__fav-cover-icon" aria-hidden="true">${icon}</span>`}
          </span>
          <span class="journey-builder__fav-text">
            <span class="journey-builder__fav-name">${escapeHtml(fav.name)}</span>
            <span class="journey-builder__fav-meta">${escapeHtml(meta || "Saved")}</span>
          </span>
          <span class="journey-builder__fav-plus" aria-hidden="true">${inJourney ? "✓" : "+"}</span>
        </button>
      `;
    })
    .join("");
}

function closeJourneyBuilder({ silent = false } = {}) {
  const overlay = document.getElementById("journeyBuilder");
  if (!overlay) return;
  overlay.classList.remove("is-open");
  setDetailOverlayClass("journey-builder-open", false);
  if (!silent && builderState.pickMode) {
    deactivateBuilderPickMode({ reopen: false });
  }
  if (!silent) {
    // User explicitly dismissed the builder — clear the "reopen after story"
    // flag so a subsequent place-story close (e.g. from a map marker tap)
    // doesn't resurrect the builder.
    builderState.reopenAfterStory = false;
  }
  window.setTimeout(() => {
    if (!overlay.classList.contains("is-open")) {
      overlay.hidden = true;
    }
    updateBuilderFab();
  }, 280);
  updateBuilderFab();
}

function isJourneyBuilderOpen() {
  return Boolean(document.getElementById("journeyBuilder")?.classList.contains("is-open"));
}

function updateBuilderFab() {
  const fab = document.getElementById("builderResumeFab");
  if (!fab) return;
  const shouldShow =
    builderState.stops.length > 0 &&
    !isJourneyBuilderOpen() &&
    !builderState.pickMode;
  if (shouldShow) {
    fab.hidden = false;
    void fab.offsetWidth;
    fab.classList.add("is-visible");
    const count = fab.querySelector("[data-fab-count]");
    if (count) {
      count.textContent = String(builderState.stops.length);
    }
  } else {
    fab.classList.remove("is-visible");
    window.setTimeout(() => {
      if (!fab.classList.contains("is-visible")) {
        fab.hidden = true;
      }
    }, 220);
  }
}

function reopenBuilderIfPending() {
  if (builderState.reopenAfterStory) {
    builderState.reopenAfterStory = false;
    window.setTimeout(() => {
      if (!isJourneyBuilderOpen()) {
        openJourneyBuilder();
      }
    }, 80);
  }
}

async function focusBuilderStop(stop) {
  closeJourneyBuilder({ silent: true });
  setActiveView("map", { silent: true });
  map.flyTo([stop.lat, stop.lng], Math.max(map.getZoom(), 9), { duration: 0.7 });

  const hasCardKind = ["city", "park", "poi", "hike"].includes(stop.kind);
  if (!hasCardKind || !stop.id) {
    // Custom map-picked points have no detail card — leave the builder closed
    // so the user can see the spot. The resume FAB stays visible to come back.
    return;
  }

  try {
    if (stop.kind === "city") {
      const details = await fetchCityById(stop.id, { name: stop.name, country: stop.country });
      await openPlaceStory(details?.name || stop.name, details || { name: stop.name });
      builderState.reopenAfterStory = true;
    } else if (stop.kind === "park") {
      const details = await fetchParkById(stop.id);
      await openPlaceStory(details?.name || stop.name, details || { name: stop.name, kind: "park" });
      builderState.reopenAfterStory = true;
    } else if (stop.kind === "poi") {
      const details = await fetchPoiById(stop.id);
      await openPlaceStory(details?.name || stop.name, details || { name: stop.name, kind: "poi" });
      builderState.reopenAfterStory = true;
    } else if (stop.kind === "hike") {
      const details = await fetchHikeById(stop.id);
      if (details) {
        await showActiveHikeRoute(details);
        openHikeStory(details, details);
        builderState.reopenAfterStory = true;
      } else {
        openJourneyBuilder();
      }
    }
  } catch (err) {
    console.warn("focusBuilderStop failed", err);
    openJourneyBuilder();
  }
}

function setBuilderAddMode(mode) {
  const changed = builderState.addMode !== mode;
  builderState.addMode = mode;
  if (changed) scheduleSaveBuilderDraft();
  const tabs = {
    search: document.getElementById("builderModeSearch"),
    map: document.getElementById("builderModeMap"),
    favorites: document.getElementById("builderModeFavorites"),
  };
  const panels = {
    search: document.getElementById("builderSearchPanel"),
    map: document.getElementById("builderMapPickPanel"),
    favorites: document.getElementById("builderFavoritesPanel"),
  };
  Object.entries(tabs).forEach(([key, btn]) => {
    if (!btn) return;
    const active = key === mode;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  Object.entries(panels).forEach(([key, panel]) => {
    if (!panel) return;
    panel.hidden = key !== mode;
  });
  if (mode === "search") {
    requestAnimationFrame(() => document.getElementById("builderSearchInput")?.focus());
  }
  if (mode === "favorites") {
    renderBuilderFavorites();
  }
}

// ----------------------------------------------------------------------------
// Map-pick mode: click anywhere (or any marker) to push a stop into the builder
// ----------------------------------------------------------------------------

const BUILDER_PICK_DRAG_THRESHOLD_PX = 6;
const builderPickPointer = { downX: 0, downY: 0, downTs: 0, dragging: false };

function activateBuilderPickMode() {
  if (builderState.pickMode) {
    return;
  }
  builderState.pickMode = true;
  closeJourneyBuilder({ silent: true });
  document.body.classList.add("is-builder-picking");
  const banner = document.getElementById("builderPickBanner");
  if (banner) {
    banner.hidden = false;
    void banner.offsetWidth;
    banner.classList.add("is-visible");
  }
  setActiveView("map", { silent: true });
  if (map?._container) {
    map._container.addEventListener("pointerdown", handleBuilderPickPointerDown, true);
    map._container.addEventListener("pointerup", handleBuilderPickPointerUp, true);
    map._container.addEventListener("click", handleBuilderMapPickClick, true);
  }
  map?.on?.("dragstart", handleBuilderPickDragStart);
  map?.on?.("movestart", handleBuilderPickDragStart);
  document.addEventListener("keydown", handleBuilderPickEscape);
}

function deactivateBuilderPickMode({ reopen = true } = {}) {
  if (!builderState.pickMode) {
    if (reopen) {
      openJourneyBuilder();
    }
    return;
  }
  builderState.pickMode = false;
  builderPickPointer.dragging = false;
  document.body.classList.remove("is-builder-picking");
  const banner = document.getElementById("builderPickBanner");
  if (banner) {
    banner.classList.remove("is-visible");
    window.setTimeout(() => {
      if (!builderState.pickMode) {
        banner.hidden = true;
      }
    }, 240);
  }
  if (map?._container) {
    map._container.removeEventListener("pointerdown", handleBuilderPickPointerDown, true);
    map._container.removeEventListener("pointerup", handleBuilderPickPointerUp, true);
    map._container.removeEventListener("click", handleBuilderMapPickClick, true);
  }
  map?.off?.("dragstart", handleBuilderPickDragStart);
  map?.off?.("movestart", handleBuilderPickDragStart);
  document.removeEventListener("keydown", handleBuilderPickEscape);
  if (reopen) {
    openJourneyBuilder();
  }
}

function handleBuilderPickEscape(event) {
  if (event.key === "Escape" && builderState.pickMode) {
    deactivateBuilderPickMode({ reopen: true });
  }
}

function handleBuilderPickDragStart() {
  builderPickPointer.dragging = true;
}

function handleBuilderPickPointerDown(event) {
  builderPickPointer.downX = event.clientX;
  builderPickPointer.downY = event.clientY;
  builderPickPointer.downTs = performance.now();
  builderPickPointer.dragging = false;
}

function handleBuilderPickPointerUp(event) {
  const dx = event.clientX - builderPickPointer.downX;
  const dy = event.clientY - builderPickPointer.downY;
  if (Math.sqrt(dx * dx + dy * dy) > BUILDER_PICK_DRAG_THRESHOLD_PX) {
    builderPickPointer.dragging = true;
  }
}

function handleBuilderMapPickClick(event) {
  if (!builderState.pickMode) {
    return;
  }
  // Don't pick a stop if this click is the tail end of a pan/drag.
  const dx = event.clientX - builderPickPointer.downX;
  const dy = event.clientY - builderPickPointer.downY;
  const moved = Math.sqrt(dx * dx + dy * dy);
  if (builderPickPointer.dragging || moved > BUILDER_PICK_DRAG_THRESHOLD_PX) {
    builderPickPointer.dragging = false;
    return;
  }
  handleBuilderMapPickAt(event.clientX, event.clientY, event);
}

function handleBuilderMapPickAt(clientX, clientY, originalEvent) {
  if (!map?._container) return;
  if (originalEvent) {
    L.DomEvent.stop(originalEvent);
  }
  const containerRect = map._container.getBoundingClientRect();
  const containerPoint = L.point(clientX - containerRect.left, clientY - containerRect.top);
  const latlng = map.containerPointToLatLng(containerPoint);

  const nearest = findNearestCatalogMarker(containerPoint, 30);
  if (nearest) {
    addBuilderStopFromMarker(nearest);
  } else {
    void addBuilderStopFromLatLng(latlng);
  }
  deactivateBuilderPickMode({ reopen: true });
}

function findNearestCatalogMarker(originPoint, maxPixels) {
  let best = null;
  const consider = (markerMap, kind) => {
    if (!markerMap) return;
    markerMap.forEach((marker) => {
      const latlng = marker.getLatLng?.();
      if (!latlng) return;
      const point = map.latLngToContainerPoint(latlng);
      const dx = point.x - originPoint.x;
      const dy = point.y - originPoint.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= maxPixels && (!best || dist < best.dist)) {
        best = { dist, marker, kind };
      }
    });
  };
  consider(cityCatalogMarkersInView, "city");
  consider(parkCatalogMarkersInView, "park");
  consider(poiCatalogMarkersInView, "poi");
  consider(hikeCatalogMarkersInView, "hike");
  return best;
}

function addBuilderStopFromMarker({ marker, kind }) {
  const latlng = marker.getLatLng();
  const props =
    marker._cityProps ||
    marker._parkProps ||
    marker._poiProps ||
    marker._hikeProps ||
    {};
  const stop = {
    id: props.id || `${kind}-${latlng.lat.toFixed(4)}-${latlng.lng.toFixed(4)}`,
    name: props.name || "Selected place",
    country: props.country || "",
    kind,
    tagline: props.tagline || "",
    lat: latlng.lat,
    lng: latlng.lng,
  };
  addBuilderStop(stop);
}

async function addBuilderStopFromLatLng(latlng) {
  const fallback = {
    id: `custom-${latlng.lat.toFixed(4)}-${latlng.lng.toFixed(4)}`,
    name: `Stop at ${latlng.lat.toFixed(3)}, ${latlng.lng.toFixed(3)}`,
    country: "",
    kind: "custom",
    tagline: "",
    lat: latlng.lat,
    lng: latlng.lng,
  };
  addBuilderStop(fallback);
  // try to enrich asynchronously via OSM reverse geocode
  try {
    const params = new URLSearchParams({
      lat: String(latlng.lat),
      lon: String(latlng.lng),
      format: "jsonv2",
      zoom: "10",
      "accept-language": "en",
    });
    const response = await fetch(`https://nominatim.openstreetmap.org/reverse?${params}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const data = await response.json();
    const addr = data?.address || {};
    const placeName =
      addr.city ||
      addr.town ||
      addr.village ||
      addr.municipality ||
      addr.county ||
      addr.state ||
      data?.name ||
      null;
    const country = addr.country || "";
    if (!placeName && !country) return;
    const target = builderState.stops.find((s) => s.id === fallback.id);
    if (!target) return;
    if (placeName) {
      target.name = placeName;
    }
    if (country) {
      target.country = country;
    }
    renderBuilderStops();
  } catch (err) {
    // network errors are non-fatal — we keep the lat/lng label
    console.warn("Reverse geocode failed", err);
  }
}

async function runBuilderSearch(query) {
  const trimmed = (query || "").trim();
  const resultsEl = document.getElementById("builderSearchResults");
  if (!resultsEl) return;
  if (trimmed.length < 2) {
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    return;
  }
  const token = ++builderState.searchToken;
  try {
    const [cityHits, parkHits, hikeHits, poiHits] = await Promise.all([
      searchPlaces(trimmed, { regionId: "europe", countries: mapSearchCountries, cityLimit: 6, countryLimit: 0 }).catch(() => []),
      searchParks(trimmed, { regionId: "europe", limit: 4 }).catch(() => []),
      searchHikes(trimmed, { regionId: "europe", limit: 4 }).catch(() => []),
      searchPois(trimmed, { regionId: "europe", limit: 4 }).catch(() => []),
    ]);
    if (token !== builderState.searchToken) return;
    const placeRows = (cityHits || [])
      .filter((row) => row.type !== "country")
      .map((row) => ({ kind: "city", ...row }));
    const parkRows = (parkHits || []).map((row) => ({ kind: "park", ...row }));
    const hikeRows = (hikeHits || []).map((row) => ({ kind: "hike", ...row }));
    const poiRows = (poiHits || []).map((row) => ({ kind: "poi", ...row }));
    const combined = [...placeRows, ...parkRows, ...hikeRows, ...poiRows].filter(
      (item) => Number.isFinite(item.lat) && Number.isFinite(item.lng)
    );
    if (!combined.length) {
      resultsEl.innerHTML = `<li class="city-search__empty" role="presentation">No matches</li>`;
      resultsEl.hidden = false;
      return;
    }
    resultsEl.innerHTML = combined
      .map((item) => {
        const payload = JSON.stringify({
          id: item.id,
          name: item.name,
          country: item.country || "",
          kind: item.kind,
          lat: item.lat,
          lng: item.lng,
          tagline: item.tagline || ""
        });
        return `
          <li role="presentation">
            <button type="button" class="city-search__option" data-builder-add data-payload='${escapeAttr(payload)}'>
              <span class="city-search__option-text">
                <span class="city-search__name">${escapeHtml(item.name)}</span>
                <span class="city-search__meta">${escapeHtml([item.country, item.kind].filter(Boolean).join(" · "))}</span>
              </span>
              <span class="city-search__kind">${escapeHtml(item.kind)}</span>
            </button>
          </li>
        `;
      })
      .join("");
    resultsEl.hidden = false;
  } catch (err) {
    console.warn("Builder search failed", err);
  }
}

function addBuilderStop(data) {
  if (!data || !Number.isFinite(data.lat) || !Number.isFinite(data.lng)) {
    return;
  }
  builderState.stops.push({
    id: data.id || `${data.kind}-${data.name}-${data.lat.toFixed(3)}-${data.lng.toFixed(3)}`,
    name: data.name,
    country: data.country || "",
    kind: data.kind || "stop",
    mode: data.mode || "drive",
    stopType: builderState.stops.length === 0 ? "start" : data.stopType || "city",
    tagline: data.tagline || "",
    lat: data.lat,
    lng: data.lng,
  });
  renderBuilderStops();
}

function haversineKm(a, b) {
  if (!a || !b) return 0;
  const toRad = (d) => (d * Math.PI) / 180;
  const R = 6371;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return 2 * R * Math.asin(Math.sqrt(h));
}

function updateBuilderSummary(stops) {
  const total = stops.reduce(
    (sum, stop, index) => (index === 0 ? 0 : sum + haversineKm(stops[index - 1], stop)),
    0
  );
  const countries = new Set(stops.map((s) => s.country).filter(Boolean));
  const summary = document.getElementById("builderSummary");
  if (summary) {
    summary.hidden = stops.length === 0;
  }
  const stopsEl = document.getElementById("builderSummaryStops");
  const distEl = document.getElementById("builderSummaryDistance");
  const countriesEl = document.getElementById("builderSummaryCountries");
  if (stopsEl) stopsEl.textContent = String(stops.length);
  if (distEl) distEl.textContent = Math.round(total).toLocaleString();
  if (countriesEl) countriesEl.textContent = String(countries.size);
}

function renderBuilderStops() {
  const list = document.getElementById("builderStops");
  if (!list) return;
  const stops = builderState.stops;
  if (!stops.length) {
    list.innerHTML = `
      <li class="journey-builder__placeholder">
        <span aria-hidden="true">🧭</span>
        <strong>No stops yet</strong>
        <small>Use Search or Pick on map to add your first place.</small>
      </li>
    `;
  } else {
    const pieces = [];
    stops.forEach((stop, index) => {
      const isFirst = index === 0;
      const isLast = index === stops.length - 1;
      if (!isFirst) {
        const distance = Math.round(haversineKm(stops[index - 1], stop));
        const modeIcon = MODE_EMOJI[stop.mode] || "🚗";
        pieces.push(`
          <li class="journey-builder__leg">
            <label class="journey-builder__leg-mode">
              <span class="visually-hidden">Mode to get here</span>
              <select data-stop-mode="${index}">
                ${["drive", "train", "ferry", "fly", "hike"]
                  .map((mode) => `<option value="${mode}" ${stop.mode === mode ? "selected" : ""}>${MODE_EMOJI[mode] || ""} ${mode}</option>`)
                  .join("")}
              </select>
            </label>
            <span class="journey-builder__leg-distance">${distance.toLocaleString()} km</span>
          </li>
        `);
      }
      const kindEmoji = KIND_EMOJI[stop.kind] || "📍";
      const meta = [stop.country, stop.kind].filter(Boolean).join(" · ") || "Custom point";
      pieces.push(`
        <li class="journey-builder__stop" data-kind="${escapeAttr(stop.kind || "stop")}">
          <span class="journey-builder__stop-num" aria-hidden="true">${index + 1}</span>
          <span class="journey-builder__stop-kind" aria-hidden="true">${kindEmoji}</span>
          <div class="journey-builder__stop-text">
            <strong>${escapeHtml(stop.name)}</strong>
            <span>${escapeHtml(meta)}</span>
          </div>
          <div class="journey-builder__stop-actions">
            <button type="button" data-stop-up="${index}" ${isFirst ? "disabled" : ""} aria-label="Move up">▲</button>
            <button type="button" data-stop-down="${index}" ${isLast ? "disabled" : ""} aria-label="Move down">▼</button>
            <button type="button" data-stop-focus="${index}" aria-label="Show on map">🎯</button>
            <button type="button" data-stop-remove="${index}" aria-label="Remove stop">✕</button>
          </div>
        </li>
      `);
    });
    list.innerHTML = pieces.join("");
  }
  updateBuilderSummary(stops);
  updateBuilderFab();
  renderBuilderFavorites();
  const mintBtn = document.getElementById("builderMint");
  if (mintBtn) {
    mintBtn.disabled = stops.length < 2;
  }
  const hint = document.getElementById("builderStopsHint");
  if (hint) {
    if (stops.length < 2) {
      hint.textContent = "Need at least 2 stops to mint a code.";
      hint.classList.remove("is-ready");
    } else {
      hint.textContent = `Looking good — ${stops.length} stops, ready to mint.`;
      hint.classList.add("is-ready");
    }
  }
  scheduleSaveBuilderDraft();
}

async function mintBuilderJourney() {
  if (builderState.stops.length < 2) {
    return;
  }
  const payload = {
    title: document.getElementById("builderTitle")?.value || "Untitled journey",
    description: document.getElementById("builderDescription")?.value || "",
    region: document.getElementById("builderRegion")?.value || "",
    author: document.getElementById("builderAuthor")?.value || "",
    days: Number(document.getElementById("builderDays")?.value || builderState.stops.length),
    emoji: "🧭",
    continent: "europe",
    stops: builderState.stops,
    highlights: builderState.stops.slice(0, 4).map((stop) =>
      [stop.name, stop.country].filter(Boolean).join(", ")
    ),
  };
  const mintBtn = document.getElementById("builderMint");
  if (mintBtn) mintBtn.disabled = true;
  try {
    const result = await createSharedJourney(payload);
    const code = result.code;
    const resultEl = document.getElementById("builderResult");
    const codeEl = document.getElementById("builderResultCode");
    const linkEl = document.getElementById("builderResultLink");
    if (codeEl) codeEl.textContent = code;
    const absUrl = `${window.location.origin}/?journey=${code}`;
    if (linkEl) linkEl.value = absUrl;
    if (resultEl) resultEl.hidden = false;
    addMintedJourney({
      code,
      title: payload.title,
      region: payload.region,
      emoji: payload.emoji,
      stops: payload.stops.length,
    });
    renderMintedJourneys();
  } catch (err) {
    alert(err.message || "Could not mint share code");
  } finally {
    if (mintBtn) mintBtn.disabled = false;
  }
}

let builderDraftSaveTimer = null;

function scheduleSaveBuilderDraft() {
  if (builderDraftSaveTimer) clearTimeout(builderDraftSaveTimer);
  builderDraftSaveTimer = setTimeout(saveBuilderDraft, 400);
}

function saveBuilderDraft() {
  builderDraftSaveTimer = null;
  if (!builderState.stops.length) {
    const title = document.getElementById("builderTitle")?.value || "";
    const description = document.getElementById("builderDescription")?.value || "";
    const region = document.getElementById("builderRegion")?.value || "";
    const author = document.getElementById("builderAuthor")?.value || "";
    if (!title && !description && !region && !author) {
      clearJourneyDraft();
      return;
    }
  }
  writeJourneyDraft({
    title: document.getElementById("builderTitle")?.value || "",
    description: document.getElementById("builderDescription")?.value || "",
    region: document.getElementById("builderRegion")?.value || "",
    author: document.getElementById("builderAuthor")?.value || "",
    days: document.getElementById("builderDays")?.value || "",
    addMode: builderState.addMode || "search",
    stops: builderState.stops,
  });
}

function restoreBuilderDraft() {
  const draft = readJourneyDraft();
  if (!draft) {
    renderMintedJourneys();
    return;
  }
  const stops = Array.isArray(draft.stops) ? draft.stops.filter((s) => Number.isFinite(s.lat) && Number.isFinite(s.lng)) : [];
  builderState.stops = stops;
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el && val != null) el.value = val;
  };
  setVal("builderTitle", draft.title || "");
  setVal("builderDescription", draft.description || "");
  setVal("builderRegion", draft.region || "");
  setVal("builderAuthor", draft.author || "");
  if (draft.days) setVal("builderDays", draft.days);
  if (draft.addMode) builderState.addMode = draft.addMode;
  renderBuilderStops();
  updateBuilderFab();
  renderMintedJourneys();
}

function formatMintedDate(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function renderMintedJourneys() {
  const host = document.getElementById("mintedJourneysSection");
  const list = document.getElementById("mintedJourneysList");
  if (!host || !list) return;
  const entries = readMintedJourneys();
  if (!entries.length) {
    host.hidden = true;
    list.innerHTML = "";
    return;
  }
  host.hidden = false;
  list.innerHTML = entries
    .map((entry) => {
      const emoji = entry.emoji || "🧭";
      const region = entry.region ? ` · ${escapeHtml(entry.region)}` : "";
      const dateStr = formatMintedDate(entry.createdAt);
      return `
        <article class="minted-journey" data-minted-code="${escapeAttr(entry.code)}">
          <button type="button" class="minted-journey__open" data-minted-open>
            <span class="minted-journey__emoji" aria-hidden="true">${emoji}</span>
            <span class="minted-journey__text">
              <span class="minted-journey__title">${escapeHtml(entry.title || "Untitled journey")}</span>
              <span class="minted-journey__meta">
                <code>${escapeHtml(entry.code)}</code>
                <span>${entry.stops || 0} stops${region}</span>
                ${dateStr ? `<span class="minted-journey__date">${escapeHtml(dateStr)}</span>` : ""}
              </span>
            </span>
          </button>
          <div class="minted-journey__actions">
            <button type="button" class="minted-journey__action" data-minted-copy aria-label="Copy share link for ${escapeAttr(entry.title || entry.code)}">Copy link</button>
            <button type="button" class="minted-journey__action minted-journey__action--danger" data-minted-remove aria-label="Forget code ${escapeAttr(entry.code)}">✕</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function setupMintedJourneysList() {
  const list = document.getElementById("mintedJourneysList");
  if (!list) return;
  list.addEventListener("click", (event) => {
    const card = event.target.closest("[data-minted-code]");
    if (!card) return;
    const code = card.dataset.mintedCode;
    if (!code) return;
    if (event.target.closest("[data-minted-remove]")) {
      removeMintedJourney(code);
      renderMintedJourneys();
      return;
    }
    if (event.target.closest("[data-minted-copy]")) {
      const link = `${window.location.origin}/?journey=${encodeURIComponent(code)}`;
      try {
        navigator.clipboard.writeText(link);
      } catch {
        /* ignore — fallback could be a temporary input + execCommand */
      }
      const btn = event.target.closest("[data-minted-copy]");
      if (btn) {
        const prev = btn.textContent;
        btn.textContent = "Copied";
        btn.disabled = true;
        setTimeout(() => {
          btn.textContent = prev;
          btn.disabled = false;
        }, 1200);
      }
      return;
    }
    if (event.target.closest("[data-minted-open]")) {
      closeTripOverlay();
      void openSharedJourney(code);
    }
  });
}

function setupFilters() {
  setupMapLayers();
  renderBasemapSwitcher();
  renderOverlaySwitcher();
  setupExploreCitiesToggle();
  setupExploreParksToggle();
  setupExploreHikesToggle();
  setupExplorePoisToggle();
  renderLegend();
  updateToggleUI();
  syncRouteControlsVisibility();
}

setupFilters();
setupHudNav();
setupPanelToggle();
setupContinentFilters();
setupTripOverlay();
setupMapPopups();
setupMediaLightbox();
setupPlaceStory();
setupHikeStory();
setupDetailOverlayEscape();
setupItineraryInteractions();
setupMobileUi();
setupWelcomeAndExplore();
setupCitySearch();
setupCountryDossier();
setupJourneyBuilder();
setupMintedJourneysList();
setupFavoritesUi();
setupSeasonStripInteractions();

void loadSeasonHints();
registerServiceWorker();

initializeTrips()
  .then(() => maybeOpenSharedJourneyFromUrl())
  .catch((error) => {
    console.error(error);
    const content = document.getElementById("itineraryContent");
    if (content) {
      content.innerHTML = "<p>There was an issue loading journey files.</p>";
    }
  });
