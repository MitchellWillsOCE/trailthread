import { defineConfig } from "vite";
import { citiesApiPlugin } from "./server/cities-api.js";
import { hikesApiPlugin } from "./server/hikes-api.js";
import { parksApiPlugin } from "./server/parks-api.js";
import { poiApiPlugin } from "./server/poi-api.js";
import { countryDossierApiPlugin } from "./server/country-dossier-api.js";
import { journeyCodesApiPlugin } from "./server/journey-codes-api.js";

export default defineConfig({
  plugins: [
    citiesApiPlugin(),
    hikesApiPlugin(),
    parksApiPlugin(),
    poiApiPlugin(),
    countryDossierApiPlugin(),
    journeyCodesApiPlugin()
  ]
});
