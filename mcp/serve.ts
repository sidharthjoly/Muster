/**
 * Run the MCP endpoint locally: `node mcp/serve.ts` (Node strips the types).
 *
 * `neon dev` is the deployed-shape runner, but it needs the CLI authenticated
 * against the branch. This needs nothing — the server holds no database
 * connection, so a plain Node listener is the whole local environment.
 */
import { serve } from "@hono/node-server";
import app from "./index.ts";

const port = Number(process.env.PORT || 8787);
serve({ fetch: app.fetch, port });
console.log(`muster mcp on http://127.0.0.1:${port}/mcp`);
