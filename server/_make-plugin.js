/**
 * Factory for the Vite dev-server / preview-server plugins that mount each
 * catalog handler under its URL prefix. The handlers themselves live in
 * `api/_lib/handlers/*.js` and are shared with the Vercel serverless
 * catch-all in `api/[...slug].js`, so there is one source of truth for the
 * API surface.
 */
import { sendJson } from "../api/_lib/sql-shared.js";

export function createApiPlugin({ name, urlPrefix, handle }) {
  const attach = (server) => {
    server.middlewares.use(async (req, res, next) => {
      if (!req.url?.startsWith(urlPrefix)) {
        next();
        return;
      }
      try {
        const url = new URL(req.url, "http://localhost");
        await handle(req, res, url);
      } catch (err) {
        console.error(`[${name}]`, err);
        if (!res.writableEnded) {
          sendJson(res, 500, { error: err.message || "Server error" });
        }
      }
    });
  };
  return {
    name,
    configureServer: attach,
    configurePreviewServer: attach,
  };
}
