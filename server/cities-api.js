import { createApiPlugin } from "./_make-plugin.js";
import { handleCities } from "../api/_lib/handlers/cities.js";

export function citiesApiPlugin() {
  return createApiPlugin({
    name: "cities-api",
    urlPrefix: "/api/cities",
    handle: handleCities,
  });
}
