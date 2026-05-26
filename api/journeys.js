import { handleJourneys } from "./_lib/handlers/journeys.js";
import { sendJson } from "./_lib/sql-shared.js";
export { config } from "./_lib/function-config.js";

export default async function handler(req, res) {
  try {
    const url = new URL(req.url, "http://localhost");
    await handleJourneys(req, res, url);
  } catch (err) {
    console.error("[journeys]", err);
    if (!res.headersSent) sendJson(res, 500, { error: err?.message || "Internal error" });
  }
}
