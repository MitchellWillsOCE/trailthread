/** Display amounts in AUD — converts €/EUR and $ (USD-style) markers in itinerary HTML. */

const EUR_TO_AUD = 1.65;

export function eurToAud(eur) {
  return Math.round(eur * EUR_TO_AUD);
}

export function formatAud(amount) {
  return `AUD $${amount.toLocaleString("en-AU")}`;
}

export function formatAudRange(low, high) {
  return `${formatAud(eurToAud(low))}–${formatAud(eurToAud(high))}`;
}

/**
 * Convert € amounts in rendered HTML to AUD for display.
 */
export function convertItineraryHtmlToAud(html) {
  let out = html;

  out = out.replace(/€\s*([\d,]+)\s*[–-]\s*€?\s*([\d,]+)/g, (_, a, b) => {
    const low = parseInt(a.replace(/,/g, ""), 10);
    const high = parseInt(b.replace(/,/g, ""), 10);
    return formatAudRange(low, high);
  });

  out = out.replace(/€\s*([\d,]+)/g, (_, num) => {
    const value = parseInt(num.replace(/,/g, ""), 10);
    return formatAud(eurToAud(value));
  });

  out = out.replace(/~\s*AUD\s+([\d.]+)\s+per\s+EUR/gi, "priced in AUD");
  out = out.replace(/Euro\s*\(EUR\)/gi, "Australian dollars (AUD)");
  out = out.replace(/\bEUR\b/g, "AUD");

  return out;
}
