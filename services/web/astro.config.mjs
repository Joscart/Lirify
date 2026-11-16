import { defineConfig } from "astro/config";
import node from "@astrojs/node";

// The player is server-rendered: `/api/player/*` endpoints run on this server and
// reach python-backend over gRPC (server-to-server). The browser never sees a
// database host, and Cloud Run can scale this service independently.
export default defineConfig({
  output: "server",
  adapter: node({ mode: "standalone" }),
  server: { host: true, port: 4321 },
  preview: { host: true, port: 4321 },
});
