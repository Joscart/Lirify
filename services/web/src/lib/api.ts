import type {
  ArtistPayload,
  Bootstrap,
  CourseSearchPayload,
  LyricsPayload,
  PlaylistPayload,
  SearchPayload,
  SessionPayload,
  StreamPayload,
  Track,
} from "./types";

// The browser always calls this Astro origin. `/api/player/*` is a server route:
// suggestions and radio use gRPC. Lyrics, course search and other player
// endpoints use the server-side HTTP proxy.
//
// For local hacking you can still bypass the SSR layer by pointing
// PUBLIC_API_BASE at the API container (http://HOST:8000).
const configured =
  (window as any).__LIRIFY_API__ ||
  (import.meta.env.PUBLIC_API_BASE as string | undefined) ||
  "";

export const API_BASE: string = String(configured).replace(/\/+$/, "");

export const MEDIA_BASE = API_BASE ? `${API_BASE}/api/player` : "/api/player";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith("http") ? path : `${MEDIA_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { Accept: "application/json", ...(init?.headers || {}) },
    });
  } catch (error) {
    throw new ApiError("The UPSpotify API is unreachable.", 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* plain text body */
    }
    throw new ApiError(String(detail), response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  bootstrap: () => request<Bootstrap>("/bootstrap"),
  tracks: (offset = 0, limit = 60, language = "") =>
    request<{ total: number; tracks: Track[] }>(
      `/tracks?offset=${offset}&limit=${limit}${language ? `&language=${encodeURIComponent(language)}` : ""}`,
    ),
  track: (id: string) => request<Track & { lyrics: any }>(`/track/${id}`),
  lyrics: (id: string) => request<LyricsPayload>(`/track/${id}/lyrics`),
  importPlaylist: (url: string) => request<{ job_id: string }>("/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  }),
  importStatus: (id: string) => request<{ status: string; stage: string; added: number | null; error: string | null }>(`/import/${encodeURIComponent(id)}`),
  search: (query: string, limit = 24) =>
    request<SearchPayload>(`/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  courseSearch: (query: string) =>
    request<CourseSearchPayload>(`/course-search?q=${encodeURIComponent(query)}`),
  radio: (id: string, limit = 16, seeds: string[] = []) =>
    request<{ seed: Track; recommendations: Track[]; engine?: string }>(
      `/radio/${id}?limit=${limit}${seeds.length ? `&seeds=${encodeURIComponent(seeds.join(","))}` : ""}`,
    ),
  artist: (id: string) => request<ArtistPayload>(`/artist/${encodeURIComponent(id)}`),
  artists: () => request<{ artists: any[] }>("/artists"),
  playlist: (id: string, offset = 0, limit = 200) =>
    request<PlaylistPayload>(
      `/playlist/${encodeURIComponent(id)}?offset=${offset}&limit=${limit}`,
    ),
  videos: (offset = 0, limit = 60) =>
    request<{ total: number; videos: Track[] }>(`/videos?offset=${offset}&limit=${limit}`),
  stream: (id: string, probe = false) =>
    request<StreamPayload>(`/stream/${id}${probe ? "?probe=1" : ""}`),
  session: (body: {
    video_id: string;
    position: number;
    duration?: number;
    state?: string;
  }) =>
    request<SessionPayload>("/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  sessionNow: () => request<SessionPayload>("/session"),
  proxy: (id: string) => `${MEDIA_BASE}/proxy/${id}`,
};

export function thumbFor(id: string, size: "hq" | "maxres" | "mq" = "hq"): string {
  return `https://i.ytimg.com/vi/${id}/${size}default.jpg`;
}
