/**
 * Journey storage — persists user journey state in cookies.
 *
 * Two cookies:
 *  - `tt-journey-draft`  : in-progress builder draft (stops + form fields)
 *  - `tt-journey-mints`  : list of journeys this user has minted (code + title + meta)
 *
 * Cookies are size-limited (~4KB each). We trim long text fields and store
 * only essentials so a realistic journey comfortably fits.
 */
const DRAFT_COOKIE = "tt-journey-draft";
const MINTS_COOKIE = "tt-journey-mints";

const DRAFT_TTL_SEC = 60 * 60 * 24 * 30; // 30 days
const MINTS_TTL_SEC = 60 * 60 * 24 * 365; // 365 days

const MAX_DRAFT_BYTES = 3800; // leave headroom under 4KB cookie cap
const MAX_MINTS_BYTES = 3800;
const MAX_MINTS = 50;

function isBrowser() {
  return typeof document !== "undefined" && typeof document.cookie === "string";
}

function setCookie(name, value, maxAgeSec) {
  if (!isBrowser()) return;
  const encoded = encodeURIComponent(value);
  const attrs = [
    `${name}=${encoded}`,
    "Path=/",
    `Max-Age=${maxAgeSec}`,
    "SameSite=Lax",
  ];
  if (window.location.protocol === "https:") {
    attrs.push("Secure");
  }
  document.cookie = attrs.join("; ");
}

function getCookie(name) {
  if (!isBrowser()) return "";
  const parts = document.cookie ? document.cookie.split(";") : [];
  for (const part of parts) {
    const [rawName, ...rest] = part.trim().split("=");
    if (rawName === name) {
      try {
        return decodeURIComponent(rest.join("="));
      } catch {
        return "";
      }
    }
  }
  return "";
}

function clearCookie(name) {
  if (!isBrowser()) return;
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
}

function safeParse(raw, fallback) {
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw);
    return parsed != null ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function trim(text, max) {
  if (!text) return "";
  const s = String(text);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function compactStop(stop) {
  return {
    id: trim(stop.id, 80),
    name: trim(stop.name, 80),
    country: trim(stop.country || "", 40),
    kind: trim(stop.kind || "stop", 16),
    mode: trim(stop.mode || "drive", 12),
    stopType: trim(stop.stopType || "city", 16),
    tagline: trim(stop.tagline || "", 80),
    lat: Number(stop.lat),
    lng: Number(stop.lng),
  };
}

function fitsCookie(payload, max) {
  return encodeURIComponent(payload).length <= max;
}

/* ---------------- Draft ---------------- */

export function readJourneyDraft() {
  const raw = getCookie(DRAFT_COOKIE);
  const data = safeParse(raw, null);
  if (!data || typeof data !== "object") return null;
  if (!Array.isArray(data.stops)) return null;
  return data;
}

export function writeJourneyDraft(draft) {
  if (!draft || typeof draft !== "object") {
    clearCookie(DRAFT_COOKIE);
    return false;
  }
  const trimmed = {
    title: trim(draft.title || "", 100),
    description: trim(draft.description || "", 280),
    region: trim(draft.region || "", 80),
    author: trim(draft.author || "", 60),
    days: Number.isFinite(Number(draft.days)) ? Number(draft.days) : null,
    addMode: trim(draft.addMode || "search", 16),
    stops: Array.isArray(draft.stops) ? draft.stops.map(compactStop) : [],
    updatedAt: Date.now(),
  };
  let payload = JSON.stringify(trimmed);
  // If too large, progressively drop taglines, then countries, then return false.
  if (!fitsCookie(payload, MAX_DRAFT_BYTES)) {
    trimmed.stops = trimmed.stops.map((s) => ({ ...s, tagline: "" }));
    payload = JSON.stringify(trimmed);
  }
  if (!fitsCookie(payload, MAX_DRAFT_BYTES)) {
    trimmed.description = "";
    payload = JSON.stringify(trimmed);
  }
  if (!fitsCookie(payload, MAX_DRAFT_BYTES)) {
    return false;
  }
  setCookie(DRAFT_COOKIE, payload, DRAFT_TTL_SEC);
  return true;
}

export function clearJourneyDraft() {
  clearCookie(DRAFT_COOKIE);
}

/* ---------------- Minted codes history ---------------- */

const TOKENS_STORAGE_KEY = "tt-journey-tokens";
const MAX_TOKENS = 50;

function readInlineTokenMap() {
  if (!isBrowser() || typeof localStorage === "undefined") return {};
  try {
    const raw = localStorage.getItem(TOKENS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeInlineTokenMap(map) {
  if (!isBrowser() || typeof localStorage === "undefined") return;
  try {
    const entries = Object.entries(map || {}).slice(0, MAX_TOKENS);
    if (!entries.length) {
      localStorage.removeItem(TOKENS_STORAGE_KEY);
      return;
    }
    const next = Object.fromEntries(entries);
    localStorage.setItem(TOKENS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* quota exceeded — silently drop the tokens, the URL on the
     * builder result still has the inline payload. */
  }
}

export function getInlineTokenForCode(code) {
  const target = String(code || "").toUpperCase();
  if (!target) return "";
  const map = readInlineTokenMap();
  return map[target] || "";
}

export function setInlineTokenForCode(code, token) {
  const target = String(code || "").toUpperCase();
  if (!target) return;
  const map = readInlineTokenMap();
  if (token) {
    map[target] = String(token);
  } else {
    delete map[target];
  }
  writeInlineTokenMap(map);
}

function clearInlineTokenForCode(code) {
  setInlineTokenForCode(code, "");
}

export function readMintedJourneys() {
  const raw = getCookie(MINTS_COOKIE);
  const data = safeParse(raw, []);
  if (!Array.isArray(data)) return [];
  const tokens = readInlineTokenMap();
  return data
    .filter((entry) => entry && entry.code)
    .map((entry) => ({
      ...entry,
      inlineToken: tokens[String(entry.code).toUpperCase()] || "",
    }));
}

function writeMintedJourneys(list) {
  let trimmed = (list || []).slice(0, MAX_MINTS).map((entry) => ({
    code: trim(entry.code || "", 14),
    title: trim(entry.title || "Untitled journey", 80),
    region: trim(entry.region || "", 60),
    emoji: trim(entry.emoji || "🧭", 4),
    stops: Number(entry.stops) || 0,
    createdAt: Number(entry.createdAt) || Date.now(),
  }));

  let payload = JSON.stringify(trimmed);
  while (trimmed.length && !fitsCookie(payload, MAX_MINTS_BYTES)) {
    trimmed.pop();
    payload = JSON.stringify(trimmed);
  }
  if (!trimmed.length) {
    clearCookie(MINTS_COOKIE);
    return [];
  }
  setCookie(MINTS_COOKIE, payload, MINTS_TTL_SEC);
  return trimmed;
}

export function addMintedJourney(entry) {
  if (!entry?.code) return readMintedJourneys();
  const code = String(entry.code).toUpperCase();
  // Inline tokens are kept in localStorage rather than the cookie because
  // they can be ~1–4KB each — too big to coexist with up to 50 mint
  // entries inside the 4KB cookie budget.
  if (entry.inlineToken) {
    setInlineTokenForCode(code, entry.inlineToken);
  }
  const existing = readMintedJourneys().filter((m) => m.code !== code);
  const next = [
    {
      ...entry,
      code,
      inlineToken: undefined,
      createdAt: entry.createdAt || Date.now(),
    },
    ...existing,
  ];
  writeMintedJourneys(next);
  return readMintedJourneys();
}

export function removeMintedJourney(code) {
  const target = String(code || "").toUpperCase();
  clearInlineTokenForCode(target);
  const next = readMintedJourneys().filter((m) => m.code !== target);
  writeMintedJourneys(next);
  return readMintedJourneys();
}

export function clearMintedJourneys() {
  clearCookie(MINTS_COOKIE);
  if (isBrowser() && typeof localStorage !== "undefined") {
    try {
      localStorage.removeItem(TOKENS_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }
}
