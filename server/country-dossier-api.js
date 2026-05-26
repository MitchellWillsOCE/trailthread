import { createApiPlugin } from "./_make-plugin.js";
import { handleCountry } from "../api/_lib/handlers/country.js";

export function countryDossierApiPlugin() {
  return createApiPlugin({
    name: "country-dossier-api",
    urlPrefix: "/api/country/",
    handle: handleCountry,
  });
}
