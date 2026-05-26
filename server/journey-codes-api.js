import { createApiPlugin } from "./_make-plugin.js";
import { handleJourneys } from "../api/_lib/handlers/journeys.js";

export function journeyCodesApiPlugin() {
  return createApiPlugin({
    name: "journey-codes-api",
    urlPrefix: "/api/journeys",
    handle: handleJourneys,
  });
}
