import { createApiPlugin } from "./_make-plugin.js";
import { handleParks } from "../api/_lib/handlers/parks.js";

export function parksApiPlugin() {
  return createApiPlugin({
    name: "parks-api",
    urlPrefix: "/api/parks",
    handle: handleParks,
  });
}
