import { createApiPlugin } from "./_make-plugin.js";
import { handleHikes } from "../api/_lib/handlers/hikes.js";

export function hikesApiPlugin() {
  return createApiPlugin({
    name: "hikes-api",
    urlPrefix: "/api/hikes",
    handle: handleHikes,
  });
}
