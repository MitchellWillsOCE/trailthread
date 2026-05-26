/** Transforms parsed itinerary HTML into sectioned timeline cards. */
import { escapeHtml } from "./media.js";

function slugifyHeading(text) {
  return String(text)
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function applyItinerarySectionModifier(section, title) {
  const lower = title.toLowerCase();
  if (/daily|day.by.day/.test(lower)) {
    section.classList.add("itinerary-section--schedule");
  } else if (/overview|budget|cost/.test(lower)) {
    section.classList.add("itinerary-section--overview");
  } else if (/hiking|trek|walk|module|trail/.test(lower)) {
    section.classList.add("itinerary-section--hikes");
  } else if (/logistics|notes|packing|tips/.test(lower)) {
    section.classList.add("itinerary-section--notes");
  } else if (/focus|theme|highlight/.test(lower)) {
    section.classList.add("itinerary-section--focus");
  }
}

function wrapItinerarySections(container) {
  container.querySelectorAll(":scope > hr").forEach((hr) => hr.remove());

  const h1 = container.querySelector(":scope > h1");
  if (h1) {
    h1.classList.add("itinerary-title");
  }

  let lead = null;
  let i = 0;

  while (i < container.children.length) {
    const el = container.children[i];

    if (el === lead) {
      i += 1;
      continue;
    }

    if (el.tagName === "H1") {
      i += 1;
      continue;
    }

    if (el.tagName === "H2") {
      const section = document.createElement("section");
      section.className = "itinerary-section";
      const slug = slugifyHeading(el.textContent);
      if (slug) {
        section.id = `itinerary-${slug}`;
      }
      applyItinerarySectionModifier(section, el.textContent);
      el.classList.add("itinerary-section__heading");
      container.insertBefore(section, el);
      section.appendChild(el);
      i += 1;
      while (
        i < container.children.length &&
        container.children[i].tagName !== "H2" &&
        container.children[i].tagName !== "H1"
      ) {
        section.appendChild(container.children[i]);
      }
      continue;
    }

    if (!lead) {
      lead = document.createElement("div");
      lead.className = "itinerary-lead";
      container.insertBefore(lead, el);
    }

    lead.appendChild(el);

    if (container.children[i] === lead) {
      i += 1;
    }
  }
}

function enhanceOverviewStats(section) {
  section.querySelectorAll(":scope > p").forEach((paragraph) => {
    const html = paragraph.innerHTML;
    if (!html.includes("|") && !/<strong>/.test(html)) {
      return;
    }

    const grid = document.createElement("div");
    grid.className = "itinerary-stat-grid";
    html.split(/\s*\|\s*/).forEach((chunk) => {
      const trimmed = chunk.trim();
      if (!trimmed) {
        return;
      }
      const cell = document.createElement("div");
      cell.className = "itinerary-stat";
      cell.innerHTML = trimmed;
      grid.appendChild(cell);
    });
    paragraph.replaceWith(grid);
  });
}

export function convertScheduleTableToTimeline(table) {
  const timeline = document.createElement("div");
  timeline.className = "itinerary-timeline";
  timeline.setAttribute("role", "list");

  table.querySelectorAll("tbody tr").forEach((row) => {
    const cells = [...row.querySelectorAll("td")];
    if (!cells.length) {
      return;
    }

    const dayRaw = cells[0]?.textContent.trim() || "";
    const dayNum = dayRaw.match(/\d+/)?.[0] || dayRaw;
    const place = cells[1]?.textContent.trim() || "";
    const activityHtml = cells[2]?.innerHTML?.trim() || "";
    const cost = cells[3]?.textContent.trim() || "";

    const card = document.createElement("article");
    card.className = "itinerary-day-card";
    if (place) {
      card.dataset.placeName = place;
      card.tabIndex = 0;
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", `Day ${dayNum}, ${place}. View on map.`);
    } else {
      card.setAttribute("role", "listitem");
    }

    card.innerHTML = `
      <div class="itinerary-day-card__rail" aria-hidden="true">
        <span class="itinerary-day-card__num">${escapeHtml(dayNum)}</span>
        <span class="itinerary-day-card__stem"></span>
      </div>
      <div class="itinerary-day-card__content">
        <div class="itinerary-day-card__header">
          <span class="itinerary-day-card__label">Day ${escapeHtml(dayNum)}</span>
          ${cost ? `<span class="itinerary-day-card__cost">${escapeHtml(cost)}</span>` : ""}
        </div>
        ${place ? `<h4 class="itinerary-day-card__place">${escapeHtml(place)}</h4>` : ""}
        ${activityHtml ? `<div class="itinerary-day-card__activity">${activityHtml}</div>` : ""}
        ${place ? `<span class="itinerary-day-card__action">View on map</span>` : ""}
      </div>
    `;

    timeline.appendChild(card);
  });

  table.replaceWith(timeline);
}

function wrapHikeModuleCards(container) {
  container.querySelectorAll(".itinerary-section--hikes > h3").forEach((heading) => {
    if (heading.closest(".hike-module")) {
      return;
    }

    const card = document.createElement("article");
    card.className = "hike-module";
    heading.classList.add("hike-module__title");
    heading.replaceWith(card);
    card.appendChild(heading);

    let sibling = card.nextElementSibling;
    while (sibling && sibling.tagName !== "H2" && sibling.tagName !== "H3") {
      const next = sibling.nextElementSibling;
      card.appendChild(sibling);
      sibling = next;
    }

    const firstPara = card.querySelector("p");
    if (firstPara && /difficulty|duration|distance/i.test(firstPara.textContent)) {
      firstPara.classList.add("hike-module__meta");
    }
  });
}

function enhanceBudgetList(container) {
  container.querySelectorAll(".itinerary-section--overview h3, .itinerary-section h3").forEach((heading) => {
    if (heading.closest(".hike-module") || !/budget/i.test(heading.textContent)) {
      return;
    }
    if (heading.nextElementSibling?.tagName !== "UL") {
      return;
    }

    const list = heading.nextElementSibling;
    const grid = document.createElement("div");
    grid.className = "budget-grid";
    list.querySelectorAll("li").forEach((item) => {
      const cell = document.createElement("div");
      cell.className = "budget-item";
      const text = item.textContent.trim();
      const split = text.match(/^([^:]+):\s*(.+)$/);
      if (split) {
        cell.innerHTML = `<span class="budget-item__label">${escapeHtml(split[1].trim())}</span><span class="budget-item__value">${escapeHtml(split[2].trim())}</span>`;
      } else {
        cell.textContent = text;
      }
      grid.appendChild(cell);
    });
    heading.classList.add("budget-section__title");
    list.replaceWith(grid);
  });
}

function buildItineraryJumpNav(container) {
  const headings = [...container.querySelectorAll(".itinerary-section > .itinerary-section__heading")];
  if (headings.length < 2) {
    return;
  }

  const nav = document.createElement("nav");
  nav.className = "itinerary-jump";
  nav.setAttribute("aria-label", "Jump to section");

  const shortLabels = {
    schedule: "Days",
    overview: "Overview",
    hikes: "Hikes",
    notes: "Logistics",
    focus: "Focus"
  };

  headings.forEach((heading) => {
    const section = heading.closest(".itinerary-section");
    if (!section?.id) {
      return;
    }
    const link = document.createElement("a");
    link.href = `#${section.id}`;
    link.className = "itinerary-jump__link";
    const key = section.className.match(/itinerary-section--(\w+)/)?.[1];
    link.textContent = shortLabels[key] || heading.textContent.replace(/\s*&\s*cost.*/i, "").trim();
    if (link.textContent.length > 22) {
      link.textContent = `${link.textContent.slice(0, 20).trim()}…`;
    }
    nav.appendChild(link);
  });

  const anchor = container.querySelector(".itinerary-title") || container.firstElementChild;
  if (anchor) {
    anchor.insertAdjacentElement("afterend", nav);
  } else {
    container.prepend(nav);
  }
}

export function decorateItineraryPlaces(container, { placeDetails = {}, getPlacePhoto } = {}) {
  if (!getPlacePhoto || !placeDetails) {
    return;
  }

  const placeNames = Object.keys(placeDetails).sort((a, b) => b.length - a.length);

  const attachThumb = (host, match) => {
    if (!host || host.querySelector(".itinerary-day-card__thumb")) {
      return;
    }
    const photo = getPlacePhoto(match);
    if (!photo) {
      return;
    }
    const img = document.createElement("img");
    img.className = "itinerary-day-card__thumb";
    img.src = photo;
    img.alt = "";
    img.loading = "lazy";
    host.prepend(img);
    host.classList.add("has-thumb");
  };

  container.querySelectorAll(".itinerary-day-card").forEach((card) => {
    const place = card.dataset.placeName;
    if (!place) {
      return;
    }
    const match = placeNames.find((name) => place.includes(name) || name.includes(place.split("/")[0]));
    if (match) {
      card.dataset.placeName = match;
      attachThumb(card.querySelector(".itinerary-day-card__place"), match);
    }
  });
}

export function enhanceItineraryContent(container) {
  container.classList.add("itinerary-doc");
  wrapItinerarySections(container);

  container.querySelectorAll(".itinerary-section--overview").forEach(enhanceOverviewStats);
  container.querySelectorAll(".itinerary-section--schedule table, table.itinerary-schedule, table").forEach((table) => {
    if (!table.closest(".itinerary-timeline")) {
      convertScheduleTableToTimeline(table);
    }
  });
  wrapHikeModuleCards(container);
  enhanceBudgetList(container);

  container.querySelectorAll(".itinerary-section--notes ul, .itinerary-lead ul").forEach((list) => {
    list.classList.add("itinerary-checklist");
  });

  container.querySelectorAll(".itinerary-section--focus > p").forEach((p) => {
    p.classList.add("itinerary-focus-note");
  });

  buildItineraryJumpNav(container);
}
