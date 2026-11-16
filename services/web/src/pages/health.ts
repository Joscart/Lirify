import type { APIRoute } from "astro";

// Cloud Run health check. It deliberately does not touch python-backend: a cold
// python-backend should not fail the Web player's own startup probe.
//
// NOTE: on *.run.app the edge intercepts /healthz and answers with Google's own
// 404 page, so this route must not use that path.
export const prerender = false;

export const GET: APIRoute = async () =>
  new Response(
    JSON.stringify({
      status: "ok",
      service: "astro-webui",
      grpc_target: process.env.GRPC_TARGET || "unset",
      backend_configured: Boolean(process.env.PYTHON_BACKEND_URL),
    }),
    {
      status: 200,
      headers: { "content-type": "application/json; charset=utf-8" },
    },
  );
