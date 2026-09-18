/**
 * Run the MCP endpoint locally: `npm run serve` (Node strips the types).
 *
 * `wrangler dev` is the deployed-shape runner — it runs this under workerd,
 * which is what production actually is, and it is the one to reach for when the
 * bug might be about the runtime. This is the other end of that trade: a plain
 * Node listener with nothing to install or sign in to, which is enough because
 * the server holds no database connection and no bindings. It reads the same
 * published files over HTTPS that the deployed worker reads.
 */
import { serve } from "@hono/node-server";
import app from "./index.ts";

const port = Number(process.env.PORT || 8787);
serve({ fetch: app.fetch, port });
console.log(`muster mcp on http://127.0.0.1:${port}/mcp`);
