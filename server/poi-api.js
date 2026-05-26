import { createApiPlugin } from "./_make-plugin.js";
import { handlePoi } from "../api/_lib/handlers/poi.js";

export function poiApiPlugin() {
  return createApiPlugin({
    name: "poi-api",
    urlPrefix: "/api/poi",
    handle: handlePoi,
  });
}
