/**
 * Cloudflare Workers AI client (server-only).
 *
 * Query understanding for web search runs on Cloudflare:
 *
 *   - CF_WORKER_URL       your own Worker that proxies Workers AI
 *   - CF_ACCOUNT_ID + CF_API_TOKEN  direct Workers AI REST calls
 *
 * The model turns the user's phrasing into a short list of catalogue keywords.
 * Ranking stays in python-backend (gRPC Search) because the song embeddings live
 * there; Cloudflare never sees MongoDB or Qdrant credentials.
 */

const MODEL = (process.env.CF_AI_MODEL || "@cf/meta/llama-3.1-8b-instruct").trim();
const WORKER_URL = (process.env.CF_WORKER_URL || "").trim().replace(/\/+$/, "");
const ACCOUNT_ID = (process.env.CF_ACCOUNT_ID || "").trim();
const API_TOKEN = (process.env.CF_API_TOKEN || "").trim();
const TIMEOUT_MS = Number(process.env.CF_AI_TIMEOUT_MS || 6000);

const SYSTEM = [
  "You expand music search queries.",
  "Return only a JSON array of 1-3 short keyword strings (artist, song, mood).",
  "No prose, no markdown, no explanations.",
].join(" ");

export interface AiExpansion {
  keywords: string[];
  source: "worker" | "workers-ai" | "none";
}

function configured(): boolean {
  return Boolean(WORKER_URL || (ACCOUNT_ID && API_TOKEN));
}

function parseKeywords(text: string, fallback: string): string[] {
  const cleaned = text.replace(/```json|```/g, "").trim();
  const start = cleaned.indexOf("[");
  const end = cleaned.lastIndexOf("]");
  if (start >= 0 && end > start) {
    try {
      const parsed = JSON.parse(cleaned.slice(start, end + 1));
      if (Array.isArray(parsed)) {
        const out = parsed
          .map((item) => String(item).trim())
          .filter((item) => item.length >= 2 && item.length <= 80);
        if (out.length) return Array.from(new Set(out)).slice(0, 3);
      }
    } catch {
      /* fall through to a plain split */
    }
  }
  const split = cleaned
    .split(/[\n,;]+/)
    .map((item) => item.replace(/^["'\-\d.\s]+|["'\s]+$/g, "").trim())
    .filter((item) => item.length >= 2 && item.length <= 80);
  return split.length ? Array.from(new Set(split)).slice(0, 3) : [fallback];
}

async function withTimeout<T>(work: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await work(controller.signal);
  } finally {
    clearTimeout(timer);
  }
}

async function callWorker(query: string): Promise<string> {
  const response = await withTimeout((signal) =>
    fetch(WORKER_URL, {
      method: "POST",
      signal,
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ query, system: SYSTEM }),
    }),
  );
  if (!response.ok) throw new Error(`worker ${response.status}`);
  const body = (await response.json()) as Record<string, unknown>;
  if (Array.isArray(body.keywords)) return JSON.stringify(body.keywords);
  return String(body.response ?? body.result ?? body.text ?? "");
}

async function callWorkersAi(query: string): Promise<string> {
  const url = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/ai/run/${MODEL}`;
  const response = await withTimeout((signal) =>
    fetch(url, {
      method: "POST",
      signal,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${API_TOKEN}`,
      },
      body: JSON.stringify({
        messages: [
          { role: "system", content: SYSTEM },
          { role: "user", content: query },
        ],
        max_tokens: 96,
        temperature: 0.1,
      }),
    }),
  );
  if (!response.ok) throw new Error(`workers-ai ${response.status}`);
  const body = (await response.json()) as {
    result?: { response?: string };
    errors?: unknown;
  };
  return String(body.result?.response ?? "");
}

/** Expand a user query into 1-3 search keywords; never throws. */
export async function expandQuery(query: string): Promise<AiExpansion> {
  const trimmed = (query || "").trim();
  if (!trimmed || !configured()) {
    return { keywords: [trimmed], source: "none" };
  }
  try {
    const raw = WORKER_URL ? await callWorker(trimmed) : await callWorkersAi(trimmed);
    return {
      keywords: parseKeywords(raw, trimmed),
      source: WORKER_URL ? "worker" : "workers-ai",
    };
  } catch (error) {
    console.warn(`[lirify] Cloudflare AI unavailable: ${(error as Error).message}`);
    return { keywords: [trimmed], source: "none" };
  }
}
