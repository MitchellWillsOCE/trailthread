/**
 * Time-of-year guidance — client-side helpers and renderer.
 *
 * `loadSeasonHints()` lazily fetches the country season map.
 * `getCountrySeason(countryName)` returns the merged hint for a country.
 * `buildTimeOfYearHtml(country)` returns an HTML strip to drop into a detail panel.
 */
import { escapeHtml } from "./media.js";

const SEASON_PATH = "/scripts/data/country-seasons.json";
let seasonsPromise = null;
let seasonsData = null;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_INITIALS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

export async function loadSeasonHints() {
  if (seasonsData) {
    return seasonsData;
  }
  if (!seasonsPromise) {
    seasonsPromise = fetch(SEASON_PATH)
      .then((r) => (r.ok ? r.json() : { default: null, byCountry: {} }))
      .then((data) => {
        seasonsData = data;
        return data;
      })
      .catch(() => {
        seasonsData = { default: null, byCountry: {} };
        return seasonsData;
      });
  }
  return seasonsPromise;
}

export function getCountrySeason(countryName) {
  if (!seasonsData) {
    return null;
  }
  if (!countryName) {
    return seasonsData.default || null;
  }
  const direct = seasonsData.byCountry?.[countryName];
  if (direct) {
    return { ...(seasonsData.default || {}), ...direct };
  }
  return seasonsData.default || null;
}

function classifyMonth(month, hint) {
  if (!hint) return "neutral";
  if (hint.peak?.includes(month)) return "peak";
  if (hint.shoulder?.includes(month)) return "shoulder";
  if (hint.low?.includes(month)) return "low";
  return "neutral";
}

function seasonLabel(cls) {
  if (cls === "peak") return "Peak season";
  if (cls === "shoulder") return "Shoulder season";
  if (cls === "low") return "Quiet season";
  return "Open";
}

export function buildTimeOfYearHtml(country) {
  const hint = getCountrySeason(country);
  if (!hint) {
    return "";
  }

  const bestLabel = hint.best
    ? `<span class="season-strip__best"><span>Best window</span><strong>${escapeHtml(hint.best)}</strong></span>`
    : "";

  const cells = MONTHS.map((m, i) => {
    const cls = classifyMonth(m, hint);
    const weather = hint.weather?.[m];
    const tip = weather
      ? `${m} · ${seasonLabel(cls)} · high ${weather.high}°C, low ${weather.low}°C, rain ${weather.rain}mm`
      : `${m} · ${seasonLabel(cls)}`;
    let anchor = "center";
    if (i <= 1) anchor = "start";
    else if (i >= 10) anchor = "end";

    const tooltip = weather
      ? `
        <span class="season-strip__pop" role="tooltip" aria-hidden="true">
          <span class="season-strip__pop-month">${escapeHtml(m)}</span>
          <span class="season-strip__pop-temp">
            <strong>${weather.high}°</strong><span class="season-strip__pop-low">/${weather.low}°</span>
          </span>
          <span class="season-strip__pop-meta">${escapeHtml(seasonLabel(cls))} · ${weather.rain}mm rain</span>
        </span>`
      : `
        <span class="season-strip__pop" role="tooltip" aria-hidden="true">
          <span class="season-strip__pop-month">${escapeHtml(m)}</span>
          <span class="season-strip__pop-meta">${escapeHtml(seasonLabel(cls))}</span>
        </span>`;

    return `
      <li class="season-strip__slot">
        <button type="button"
                class="season-strip__cell season-strip__cell--${cls}"
                data-season-cell
                data-anchor="${anchor}"
                aria-label="${escapeHtml(tip)}">
          <span class="season-strip__month" aria-hidden="true">${MONTH_INITIALS[i]}</span>
          ${tooltip}
        </button>
      </li>
    `;
  }).join("");

  const legend = `
    <ul class="season-strip__legend" aria-label="Season legend">
      <li><span class="season-strip__swatch season-strip__swatch--peak" aria-hidden="true"></span>Peak</li>
      <li><span class="season-strip__swatch season-strip__swatch--shoulder" aria-hidden="true"></span>Shoulder</li>
      <li><span class="season-strip__swatch season-strip__swatch--low" aria-hidden="true"></span>Quiet</li>
    </ul>`;

  const subtitle = hint.weather
    ? `<p class="season-strip__sub">Hover or tap a month for typical weather.</p>`
    : "";

  return `
    <section class="season-strip" aria-label="Time of year guidance" data-season-strip>
      <header class="season-strip__head">
        <h3 class="season-strip__title">When to visit</h3>
        ${bestLabel}
      </header>
      ${subtitle}
      <ol class="season-strip__grid" role="list">${cells}</ol>
      ${legend}
      ${hint.note ? `<p class="season-strip__note">${escapeHtml(hint.note)}</p>` : ""}
    </section>
  `;
}
