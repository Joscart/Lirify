/**
 * Web search: Cloudflare Workers AI understands the query, python-backend ranks.
 *
 * The embeddings that drive recommendations and radio are the LLM embeddings the
 * local indexer publishes to Qdrant, so only python-backend can rank them. The
 * Worker therefore expands the query into catalogue keywords; we run one gRPC
 * Search per keyword and merge by best score.
 */

import { expandQuery } from "./cloudflare";
import { search, type SearchPayload } from "./grpc";

export interface AiSearchPayload extends SearchPayload {
  ai_source: "worker" | "workers-ai" | "none";
  keywords: string[];
}

const SEMANTIC = (process.env.SEMANTIC_SEARCH || "").toLowerCase() === "true";

export async function searchWithAi(query: string, limit = 24): Promise<AiSearchPayload> {
  // When python-backend embeds the query with Qwen3 (QUERY_EMBED_URL), send the
  // raw query: no keyword rewriting, so the vector matches the indexed lyrics.
  if (SEMANTIC) {
    const payload = await search((query || "").trim(), limit);
    return { ...payload, ai_source: "none", keywords: [(query || "").trim()] };
  }
  const expansion = await expandQuery(query);
  const keywords = expansion.keywords.length ? expansion.keywords : [query];

  if (keywords.length === 1) {
    const payload = await search(keywords[0], limit);
    return {
      ...payload,
      query,
      ai_source: expansion.source,
      keywords,
    };
  }

  const perKeyword = Math.max(limit, 8);
  const responses = await Promise.all(
    keywords.map((keyword) => search(keyword, perKeyword).catch(() => null)),
  );

  const best = new Map<string, (SearchPayload["tracks"][number])>();
  for (const response of responses) {
    if (!response) continue;
    for (const track of response.tracks) {
      const previous = best.get(track.video_id);
      if (!previous || (track.score || 0) > (previous.score || 0)) {
        best.set(track.video_id, track);
      }
    }
  }

  const tracks = Array.from(best.values())
    .sort((left, right) => (right.score || 0) - (left.score || 0))
    .slice(0, limit);

  return {
    query,
    top: tracks[0] || null,
    tracks,
    artists: [],
    snippet: keywords.length > 1 ? `Cloudflare AI: ${keywords.join(" · ")}` : "",
    scanned: responses.reduce((total, row) => total + (row?.scanned || 0), 0),
    ai_source: expansion.source,
    keywords,
  };
}
