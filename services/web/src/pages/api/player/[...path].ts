/**
 * Astro SSR gate in front of python-backend.
 *
 *   GET  /api/player/search?q=...        -> gRPC Search
 *   GET  /api/player/radio/{videoId}     -> gRPC Recommend (seeds come from the browser)
 *   GET  /api/player/track/{id}/lyrics   -> gRPC GetLyrics
 *   *    /api/player/<anything else>     -> server-side HTTP proxy to python-backend
 *
 * The course search, catalogue, import, lyrics, stream and playback sessions go through the
 * HTTP proxy. The browser talks to the Astro origin for both transports.
 */

import type { APIRoute } from "astro";

import { recommend, search } from "../../../lib/grpc";

export const prerender = false;

const BACKEND = (process.env.PYTHON_BACKEND_URL || "").replace(/\/+$/, "");
const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function failure(error: unknown): Response {
  const code = (error as { code?: number }).code;
  const message = error instanceof Error ? error.message : String(error);
  const status = code === 5 ? 404 : code === 3 ? 400 : 503; // NOT_FOUND / INVALID_ARGUMENT / other
  return json({ detail: `python-backend gRPC error: ${message}`, code }, status);
}

async function proxy(request: Request, url: URL, path: string): Promise<Response> {
  if (!BACKEND) {
    return json(
      { detail: "PYTHON_BACKEND_URL is not configured for astro-webui" },
      503,
    );
  }
  const target = new URL(`${BACKEND}/api/player/${path}`);
  target.search = url.search;

  const headers = new Headers();
  for (const name of ["accept", "content-type", "range", "if-range"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: "manual",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  const out = new Headers();
  for (const name of [
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "cache-control",
    "etag",
    "last-modified",
  ]) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  out.set("x-lirify-upstream", "python-backend");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const ALL: APIRoute = async ({ params, request, url }) => {
  const path = (params.path || "").replace(/^\/+/, "");

  // --- gRPC: search -------------------------------------------------------
  if (request.method === "GET" && path === "search") {
    const query = url.searchParams.get("q") || "";
    const limit = Number(url.searchParams.get("limit") || 24);
    if (!query.trim()) return json({ query, top: null, tracks: [], artists: [], snippet: "", scanned: 0 });
    try {
      const payload = await search(query, limit);
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { ...JSON_HEADERS, "cache-control": "no-store", "x-lirify-transport": "grpc" },
      });
    } catch (error) {
      return failure(error);
    }
  }

  // --- gRPC: recommendations ---------------------------------------------
  if (request.method === "GET" && path.startsWith("radio/")) {
    const videoId = decodeURIComponent(path.slice("radio/".length));
    const limit = Number(url.searchParams.get("limit") || 16);
    const seeds = (url.searchParams.get("seeds") || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    try {
      const payload = await recommend(videoId, seeds, limit);
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { ...JSON_HEADERS, "cache-control": "no-store", "x-lirify-transport": "grpc" },
      });
    } catch (error) {
      return failure(error);
    }
  }

  // --- everything else: server-side proxy --------------------------------
  try {
    return await proxy(request, url, path);
  } catch (error) {
    return json(
      {
        detail: `python-backend unreachable: ${error instanceof Error ? error.message : String(error)}`,
      },
      502,
    );
  }
};
