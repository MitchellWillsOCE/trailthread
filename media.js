let lightboxPhotos = [];
let lightboxIndex = 0;
let carouselUid = 0;

export function coercePhotos(photos) {
  if (Array.isArray(photos)) {
    return photos;
  }
  if (typeof photos === "string" && photos.trim()) {
    try {
      const parsed = JSON.parse(photos);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

export function resolvePhotoUrl(url) {
  if (!url) {
    return "";
  }
  let trimmed = String(url).trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.startsWith("//")) {
    trimmed = `https:${trimmed}`;
  }
  if (/^Trip\/media\//i.test(trimmed)) {
    trimmed = `/${trimmed}`;
  } else if (trimmed.startsWith("./Trip/")) {
    trimmed = trimmed.slice(1);
  }
  // Direct CDN / upload URLs — keep stored thumb size (upscaling can 400 on Wikimedia).
  if (/upload\.wikimedia\.org/i.test(trimmed)) {
    return trimmed;
  }
  // Commons FilePath redirects work in <img>; keep encoded path intact
  return trimmed;
}

/**
 * Collapse different URL forms that point at the same underlying photo (e.g.
 * Wikimedia's `Special:FilePath` redirect vs. an `upload.wikimedia.org` thumb)
 * down to a single fingerprint string so duplicates can be detected.
 */
export function photoFingerprint(url) {
  if (!url) return "";
  let s = String(url).trim().toLowerCase();
  if (!s) return "";
  s = s.replace(/^https?:/, "");
  try {
    s = decodeURIComponent(s);
  } catch {
    /* ignore decode errors */
  }

  let m = s.match(/special:filepath\/([^?#]+)/);
  if (m) return m[1].replace(/_/g, " ").trim();

  m = s.match(/\/wikipedia\/[a-z]+\/thumb\/[^/]+\/[^/]+\/([^/]+)\/\d+px-/);
  if (m) return m[1].replace(/_/g, " ").trim();

  m = s.match(/\/wikipedia\/[a-z]+\/[^/]+\/[^/]+\/([^/?#]+)$/);
  if (m && !/thumb/.test(s)) return m[1].replace(/_/g, " ").trim();

  return s.replace(/[?#].*$/, "").trim();
}

/**
 * Remove duplicate photo entries (different size variants of the same file
 * collapse to one). Preserves order of first occurrence.
 */
export function dedupePhotoEntries(entries) {
  if (!Array.isArray(entries)) return [];
  const seen = new Set();
  const out = [];
  for (const entry of entries) {
    if (!entry?.url) continue;
    const key = photoFingerprint(entry.url);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(entry);
  }
  return out;
}

const PLACE_EMOJI_KEYWORDS = [
  ["national park", "🌲"],
  ["nature park", "🌲"],
  ["palace", "🏰"],
  ["castle", "🏰"],
  ["fortress", "🏯"],
  ["citadel", "🏯"],
  ["cathedral", "⛪"],
  ["basilica", "⛪"],
  ["chapel", "⛪"],
  ["church", "⛪"],
  ["abbey", "⛪"],
  ["monastery", "🛕"],
  ["mosque", "🕌"],
  ["synagogue", "🕍"],
  ["temple", "🛕"],
  ["shrine", "⛩️"],
  ["museum", "🏛️"],
  ["gallery", "🖼️"],
  ["library", "📚"],
  ["opera", "🎭"],
  ["theatre", "🎭"],
  ["theater", "🎭"],
  ["bridge", "🌉"],
  ["tower", "🗼"],
  ["statue", "🗿"],
  ["monument", "🗿"],
  ["lighthouse", "🌅"],
  ["mountain", "⛰️"],
  ["peak", "⛰️"],
  ["alps", "⛰️"],
  ["volcano", "🌋"],
  ["canyon", "🏔️"],
  ["valley", "🏞️"],
  ["gorge", "🏞️"],
  ["lake", "🌊"],
  ["river", "🏞️"],
  ["waterfall", "💦"],
  ["fjord", "🌊"],
  ["beach", "🏖️"],
  ["coast", "🏖️"],
  ["riviera", "🏖️"],
  ["island", "🏝️"],
  ["bay", "🌊"],
  ["forest", "🌳"],
  ["woods", "🌲"],
  ["desert", "🏜️"],
  ["glacier", "🧊"],
  ["cave", "🕳️"],
  ["garden", "🌷"],
  ["park", "🌳"],
  ["trail", "🥾"],
  ["path", "🥾"],
  ["camino", "🥾"],
  ["village", "🏘️"],
  ["town", "🏘️"]
];

export function emojiForPlace(name = "", kind = "") {
  const n = String(name || "").toLowerCase();
  for (const [needle, emoji] of PLACE_EMOJI_KEYWORDS) {
    if (n.includes(needle)) return emoji;
  }
  if (kind === "park") return "🌲";
  if (kind === "poi") return "🏛️";
  if (kind === "hike") return "🥾";
  if (kind === "city") return "🏙️";
  return "🗺️";
}

export function buildEmojiHeroHtml({ emoji, title = "", subtitle = "", variant = "dest" } = {}) {
  const glyph = emoji || "🗺️";
  return `
    <div class="media-carousel media-carousel--${variant} media-carousel--emoji" data-photo-count="0" role="img" aria-label="${escapeAttr(title || "Destination")}">
      <div class="media-carousel__emoji-frame">
        <span class="media-carousel__emoji" aria-hidden="true">${glyph}</span>
        ${subtitle ? `<span class="media-carousel__emoji-sub">${escapeAttr(subtitle)}</span>` : ""}
      </div>
    </div>
  `;
}

export function normalizePhotoEntries(photos) {
  const list = coercePhotos(photos);
  if (!list.length) {
    return [];
  }

  return list
    .map((item) => {
      if (typeof item === "string") {
        return { url: resolvePhotoUrl(item), caption: "" };
      }
      return {
        url: resolvePhotoUrl(item.url || item.src || ""),
        caption: item.caption || "",
        source: item.source || ""
      };
    })
    .filter((item) => item.url);
}

export function escapeAttr(text) {
  return escapeHtml(text).replace(/'/g, "&#39;");
}

export function buildPopupHeroImageTag(photo, alt = "") {
  const url = typeof photo === "string" ? resolvePhotoUrl(photo) : resolvePhotoUrl(photo?.url);
  if (!url) {
    return "";
  }
  return `<img class="dest-popup-card__hero-img" src="${escapeAttr(url)}" alt="${escapeAttr(alt)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" />`;
}

export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function buildMediaCarouselHtml(photos, { variant = "default", title = "Place" } = {}) {
  const entries = dedupePhotoEntries(normalizePhotoEntries(photos));
  const id = `carousel-${++carouselUid}`;

  if (!entries.length) {
    return "";
  }

  const slides = entries
    .map(
      (entry, index) => `
      <figure class="media-carousel__slide" data-index="${index}">
        <button type="button" class="media-carousel__expand" data-lightbox-index="${index}" aria-label="View photo ${index + 1} full screen">
          <img src="${escapeAttr(entry.url)}" alt="${escapeAttr(entry.caption || title)}" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-photo-url="${escapeAttr(entry.url)}" />
        </button>
        ${entry.caption ? `<figcaption class="media-carousel__caption">${escapeHtml(entry.caption)}</figcaption>` : ""}
      </figure>
    `
    )
    .join("");

  const dots = entries
    .map(
      (_, index) =>
        `<button type="button" class="media-carousel__dot${index === 0 ? " is-active" : ""}" data-carousel-go="${index}" aria-label="Photo ${index + 1}"></button>`
    )
    .join("");

  const chrome =
    entries.length > 1
      ? `
      <button type="button" class="media-carousel__nav media-carousel__nav--prev" data-carousel-prev aria-label="Previous photo">‹</button>
      <button type="button" class="media-carousel__nav media-carousel__nav--next" data-carousel-next aria-label="Next photo">›</button>
      <aside class="media-carousel__rail" aria-label="Photo navigation">
        <div class="media-carousel__dots" role="tablist" aria-orientation="vertical">${dots}</div>
        <span class="media-carousel__count" data-carousel-count>1 / ${entries.length}</span>
      </aside>`
      : "";

  return `<div class="media-carousel media-carousel--${variant}" data-media-carousel data-carousel-id="${id}" data-photo-count="${entries.length}" data-active-index="0">
      <div class="media-carousel__viewport" tabindex="0" role="region" aria-label="${escapeAttr(title)} photos">
        <div class="media-carousel__track">${slides}</div>
      </div>
      ${chrome}
    </div>`;
}

function getCarouselPhotos(carousel) {
  return [...carousel.querySelectorAll(".media-carousel__slide img")].map((img, index) => ({
    url: img.getAttribute("src"),
    caption: carousel.querySelectorAll(".media-carousel__caption")[index]?.textContent || ""
  }));
}

function syncCarousel(carousel, index) {
  const viewport = carousel.querySelector(".media-carousel__viewport");
  const slides = carousel.querySelectorAll(".media-carousel__slide");
  const count = slides.length;
  if (!count) {
    return;
  }

  const safeIndex = ((index % count) + count) % count;
  const slide = slides[safeIndex];
  if (viewport && slide) {
    const left = slide.offsetLeft - (viewport.clientWidth - slide.offsetWidth) / 2;
    viewport.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
  } else {
    slide.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }

  carousel.querySelectorAll(".media-carousel__dot").forEach((dot, dotIndex) => {
    dot.classList.toggle("is-active", dotIndex === safeIndex);
  });

  const counter = carousel.querySelector("[data-carousel-count]");
  if (counter) {
    counter.textContent = `${safeIndex + 1} / ${count}`;
  }

  carousel.dataset.activeIndex = String(safeIndex);
  carousel.dispatchEvent(
    new CustomEvent("carouselchange", { bubbles: true, detail: { index: safeIndex, count } })
  );
}

function bindCarousel(carousel) {
  if (carousel.dataset.bound === "true") {
    return;
  }

  carousel.dataset.bound = "true";
  const viewport = carousel.querySelector(".media-carousel__viewport");
  const slides = carousel.querySelectorAll(".media-carousel__slide");

  const updateFromScroll = () => {
    if (!viewport || !slides.length) {
      return;
    }
    const viewportCenter = viewport.scrollLeft + viewport.clientWidth / 2;
    let closest = 0;
    let closestDist = Infinity;
    slides.forEach((slide, index) => {
      const slideCenter = slide.offsetLeft + slide.offsetWidth / 2;
      const dist = Math.abs(slideCenter - viewportCenter);
      if (dist < closestDist) {
        closestDist = dist;
        closest = index;
      }
    });
    const previous = Number(carousel.dataset.activeIndex || 0);
    carousel.querySelectorAll(".media-carousel__dot").forEach((dot, dotIndex) => {
      dot.classList.toggle("is-active", dotIndex === closest);
    });
    const counter = carousel.querySelector("[data-carousel-count]");
    if (counter) {
      counter.textContent = `${closest + 1} / ${slides.length}`;
    }
    carousel.dataset.activeIndex = String(closest);
    if (closest !== previous) {
      carousel.dispatchEvent(
        new CustomEvent("carouselchange", { bubbles: true, detail: { index: closest, count: slides.length } })
      );
    }
  };

  let scrollTimer;
  viewport?.addEventListener(
    "scroll",
    () => {
      window.clearTimeout(scrollTimer);
      scrollTimer = window.setTimeout(updateFromScroll, 60);
    },
    { passive: true }
  );

  carousel.addEventListener("click", (event) => {
    const prev = event.target.closest("[data-carousel-prev]");
    const next = event.target.closest("[data-carousel-next]");
    const dot = event.target.closest("[data-carousel-go]");
    const expand = event.target.closest("[data-lightbox-index]");

    if (prev || next || dot) {
      event.preventDefault();
      const current = Number(carousel.dataset.activeIndex || 0);
      if (dot) {
        syncCarousel(carousel, Number(dot.dataset.carouselGo));
        return;
      }
      syncCarousel(carousel, current + (next ? 1 : -1));
      return;
    }

    if (expand) {
      event.preventDefault();
      openMediaLightbox(getCarouselPhotos(carousel), Number(expand.dataset.lightboxIndex || 0));
    }
  });

  viewport?.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      syncCarousel(carousel, Number(carousel.dataset.activeIndex || 0) - 1);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      syncCarousel(carousel, Number(carousel.dataset.activeIndex || 0) + 1);
    }
  });
}

export function initMediaCarousels(root = document) {
  root.querySelectorAll("[data-media-carousel]").forEach((carousel) => {
    carousel.dataset.bound = "false";
    bindCarousel(carousel);
  });
}

export function buildHighlightsCarouselHtml(highlights, { title = "Destination", excludeUrls = null } = {}) {
  const excludeSet = excludeUrls instanceof Set ? excludeUrls : null;
  const seen = new Set();
  const items = [];
  for (const h of highlights || []) {
    if (!h?.url) continue;
    const key = photoFingerprint(h.url);
    if (!key || seen.has(key)) continue;
    if (excludeSet && excludeSet.has(key)) continue;
    seen.add(key);
    items.push(h);
  }
  const id = `highlights-${++carouselUid}`;
  if (items.length < 2) {
    return "";
  }

  const slides = items
    .map((item, index) => {
      const label = item.title || item.caption || `Highlight ${index + 1}`;
      const tilt = (index % 6) + 1;
      return `
      <li class="dest-highlights__item">
        <article class="dest-highlights__card dest-highlights__card--tilt${tilt}">
          <h4 class="dest-highlights__title">
            <button type="button" class="dest-highlights__trigger" data-lightbox-index="${index}" aria-label="View ${escapeAttr(label)}">
              <span class="dest-highlights__title-text">${escapeHtml(label)}</span>
            </button>
          </h4>
          <img class="dest-highlights__image" src="${escapeAttr(resolvePhotoUrl(item.url))}" alt="" width="232" height="285" loading="lazy" decoding="async" referrerpolicy="no-referrer" />
          <span class="dest-highlights__chevron" aria-hidden="true">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 16 16"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" d="M5.85 13.15 11.15 8l-5.3-5.15"/></svg>
          </span>
        </article>
      </li>`;
    })
    .join("");

  return `
    <div class="dest-highlights" data-dest-highlights data-highlights-id="${id}" data-active-index="0">
      <ul class="dest-highlights__list">${slides}</ul>
      <div class="dest-highlights__shadow dest-highlights__shadow--right" aria-hidden="true"></div>
      <button type="button" class="dest-highlights__nav dest-highlights__nav--next" data-highlights-next aria-label="Next highlight">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 16 16" aria-hidden="true"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.7" d="M3.848 8.85 8 13.15m0 0 4.15-4.3M8 13.15V2.85"/></svg>
      </button>
    </div>`;
}

function syncHighlightsCarousel(root, index) {
  const list = root.querySelector(".dest-highlights__list");
  const items = root.querySelectorAll(".dest-highlights__item");
  const count = items.length;
  if (!count || !list) {
    return;
  }
  const safe = ((index % count) + count) % count;
  const item = items[safe];
  const left = item.offsetLeft - 12;
  list.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
  root.dataset.activeIndex = String(safe);
  const shadow = root.querySelector(".dest-highlights__shadow--right");
  if (shadow) {
    const atEnd = safe >= count - 2;
    shadow.style.opacity = atEnd ? "0" : "1";
  }
}

function bindHighlightsCarousel(root) {
  if (root.dataset.bound === "true") {
    return;
  }
  root.dataset.bound = "true";
  const list = root.querySelector(".dest-highlights__list");
  const photos = [...root.querySelectorAll(".dest-highlights__image")].map((img, index) => ({
    url: img.getAttribute("src"),
    caption: root.querySelectorAll(".dest-highlights__title-text")[index]?.textContent || ""
  }));

  root.addEventListener("click", (event) => {
    const next = event.target.closest("[data-highlights-next]");
    const trigger = event.target.closest("[data-lightbox-index]");
    if (next) {
      event.preventDefault();
      const current = Number(root.dataset.activeIndex || 0);
      syncHighlightsCarousel(root, current + 1);
      return;
    }
    if (trigger) {
      event.preventDefault();
      openMediaLightbox(photos, Number(trigger.dataset.lightboxIndex || 0));
    }
  });

  let scrollTimer;
  list?.addEventListener(
    "scroll",
    () => {
      window.clearTimeout(scrollTimer);
      scrollTimer = window.setTimeout(() => {
        const items = root.querySelectorAll(".dest-highlights__item");
        if (!list || !items.length) {
          return;
        }
        const center = list.scrollLeft + list.clientWidth / 2;
        let closest = 0;
        let dist = Infinity;
        items.forEach((item, i) => {
          const d = Math.abs(item.offsetLeft + item.offsetWidth / 2 - center);
          if (d < dist) {
            dist = d;
            closest = i;
          }
        });
        root.dataset.activeIndex = String(closest);
        const shadow = root.querySelector(".dest-highlights__shadow--right");
        if (shadow) {
          shadow.style.opacity = closest >= items.length - 2 ? "0" : "1";
        }
      }, 80);
    },
    { passive: true }
  );
}

export function initHighlightsCarousels(root = document) {
  root.querySelectorAll("[data-dest-highlights]").forEach((el) => {
    el.dataset.bound = "false";
    bindHighlightsCarousel(el);
  });
}

export function openMediaLightbox(photos, index = 0) {
  const entries = normalizePhotoEntries(photos);
  if (!entries.length) {
    return;
  }

  lightboxPhotos = entries;
  lightboxIndex = Math.max(0, Math.min(index, entries.length - 1));

  const lightbox = document.getElementById("mediaLightbox");
  if (!lightbox) {
    return;
  }

  lightbox.hidden = false;
  lightbox.classList.add("is-open");
  document.body.classList.add("media-lightbox-open");
  renderLightboxSlide();
  lightbox.querySelector("[data-lightbox-close]")?.focus();
}

export function closeMediaLightbox() {
  const lightbox = document.getElementById("mediaLightbox");
  if (!lightbox) {
    return;
  }

  lightbox.classList.remove("is-open");
  lightbox.hidden = true;
  document.body.classList.remove("media-lightbox-open");
}

function renderLightboxSlide() {
  const entry = lightboxPhotos[lightboxIndex];
  if (!entry) {
    return;
  }

  const img = document.getElementById("mediaLightboxImage");
  const caption = document.getElementById("mediaLightboxCaption");
  const counter = document.getElementById("mediaLightboxCounter");

  if (img) {
    img.src = entry.url;
    img.alt = entry.caption || "Trip photo";
  }
  if (caption) {
    const credit = entry.source && entry.caption ? ` (${entry.source})` : entry.source || "";
    const text = `${entry.caption || ""}${credit}`.trim();
    caption.textContent = text;
    caption.hidden = !text;
  }
  if (counter) {
    counter.textContent = `${lightboxIndex + 1} / ${lightboxPhotos.length}`;
  }

  const lightbox = document.getElementById("mediaLightbox");
  lightbox?.querySelector("[data-lightbox-prev]")?.toggleAttribute("hidden", lightboxPhotos.length <= 1);
  lightbox?.querySelector("[data-lightbox-next]")?.toggleAttribute("hidden", lightboxPhotos.length <= 1);
}

function stepLightbox(delta) {
  if (!lightboxPhotos.length) {
    return;
  }
  lightboxIndex = (lightboxIndex + delta + lightboxPhotos.length) % lightboxPhotos.length;
  renderLightboxSlide();
}

export function setupMediaLightbox() {
  const lightbox = document.getElementById("mediaLightbox");
  if (!lightbox) {
    return;
  }

  lightbox.addEventListener("click", (event) => {
    if (
      event.target.closest("[data-lightbox-close]") ||
      event.target.classList.contains("media-lightbox__backdrop")
    ) {
      closeMediaLightbox();
    }
  });

  lightbox.querySelector("[data-lightbox-prev]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    stepLightbox(-1);
  });

  lightbox.querySelector("[data-lightbox-next]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    stepLightbox(1);
  });

  document.addEventListener("keydown", (event) => {
    if (!lightbox.classList.contains("is-open")) {
      return;
    }
    if (event.key === "Escape") {
      closeMediaLightbox();
    }
    if (event.key === "ArrowLeft") {
      stepLightbox(-1);
    }
    if (event.key === "ArrowRight") {
      stepLightbox(1);
    }
  });
}
