# Lirify architecture

Lirify is split into two stacks that share one gRPC contract and one pair of
databases:

* **Cloud serving** — three read-only Cloud Run services. They answer search,
  recommendations, lyrics, stats and the player, and never scrape, embed or
  write index state.
* **Local indexing** — a laptop stack (`llama.cpp` Qwen3-Embedding-0.6B +
  `local-indexer` + `local-ui`) that owns every Atlas/Qdrant write and keeps the
  Qwen3 vocabulary and inverted index on local disk.

```
CLOUD (read-only serving, three services)
                    ┌─────────────────────────────┐
  browser ──HTTPS──▶│ astro-webui   (Cloud Run)   │
                    │  SSR /api/player/*          │
                    │  gRPC client ────────────┐  │
                    └──────────────────────────┘  │
                                                  │  gRPC / TLS :443 (h2c in)
  browser ──HTTPS──▶┌─────────────────────────────┐│
                    │ go-webui      (Cloud Run)   ││
                    │  stats/health only          ││
                    │  gRPC client + SSE hub ───┐ ││
                    └──────────────────────────┘ ││
                                                 ▼▼
                    ┌──────────────────────────────────────────┐
  monitors ──HTTPS─▶ python-backend (Cloud Run, one port)      │
                    │  SERVE_ONLY=true                         │
                    │  Caddy h2c mux                           │
                    │   ├─ application/grpc → grpc.aio :50051  │
                    │   └─ everything else  → uvicorn  :8000   │
                    │                                          │
                    │  MongoDB Atlas  ◀── read-only            │
                    │  Qdrant Cloud   ◀── read-only            │
                    └──────────────────────────────────────────┘
                                      ▲
                                      │ writes (index + embeddings)
                                      │
LOCAL (laptop: RTX 2050 4 GB)         │
  local-ui (Go, :8090) ──gRPC──▶ local-indexer (Python, :50051)
                                   │  scrape → filter → dedupe → matrix
                                   │  llama.cpp embeddings ──▶ Qdrant Cloud
                                   │  songs/jobs/stats ─────▶ Atlas
                                   │
                                   ├──▶ llama-server (:8081)
                                   │      Qwen3-Embedding-0.6B (GGUF, CUDA)
                                   └──▶ local-index/
                                          vocabulary.json
                                          inverted_index.json
```

## Service boundaries

| Service | Owns | Never touches |
| --- | --- | --- |
| `python-backend` (cloud) | read-only serving of committed state; player duration persistence; revision checks | index mutations, scrapers, embedding, local disk |
| `astro-webui` | SSR + player UI; browser history | Mongo, Qdrant, index state |
| `go-webui` (cloud) | read-only stats/health dashboard; SSE fan-out of `WatchIndexStats` | Mongo, Qdrant, local disk, write RPCs |
| `local-indexer` | the full pipeline, Atlas/Qdrant writes, embedding through llama.cpp, local vocabulary + inverted index | the browser, HTTP |
| `local-ui` | the same dashboard plus index/publish controls; gRPC only | Mongo, Qdrant, business logic, scraping, embedding, local disk |
| `llama-server` | Qwen3-Embedding-0.6B inference (`/v1/embeddings`) | databases, index state |
| browser | listening history, search history, playback session | any database |

`SERVE_ONLY` is the role switch:

* `SERVE_ONLY=true` (default) — the API mounts no bot router, returns `403` on
  `/index`, `/queue`, `/extract`, `/retry`, answers `UNIMPLEMENTED` on every
  indexing RPC, starts only the revision poller, and refuses writes at
  `store.py`/`vector.py` boundaries. The Go dashboard runs
  `DASHBOARD_MODE=readonly`, hides the controls and returns `403` on the write
  routes.
* `SERVE_ONLY=false` — `local-indexer` runs the scrapers, the playlist/matrix/
  retry workers, and writes to Atlas/Qdrant. It registers the extra
  `LirifyIndexerService` for publish/local-index operations.

## Where state lives

| State | Home | Survives a cold start |
| --- | --- | --- |
| Committed tracks (title, artist, lyrics, language) | Atlas `songs` | yes |
| Lyric lookup cache (positive results only) | Atlas `lyrics_cache` | yes |
| Failed-song retry ledger | Atlas `failed_songs` | yes |
| Jobs + stashed batches | Atlas `jobs`, `stashes` | yes |
| Index statistics + `revision` | Atlas `index_stats` | yes |
| Resolved media durations | Atlas `media_durations` | yes |
| Lyric embeddings (Qwen3, 1024-dim) | Qdrant `lirify_lyrics_qwen3` | yes |
| Qwen3 vocabulary | `local-index/vocabulary.json` (laptop) | yes (laptop disk) |
| Full inverted index (term id → postings) | `local-index/inverted_index.json` (laptop) | yes (laptop disk) |
| TF-IDF matrices, in-process inverted index | process memory | no — rebuilt from Atlas on boot |
| Listening history, search history | browser `localStorage` | yes (per browser) |
| Playback clock, in-flight jobs | process memory | no — acceptable |

The cloud containers still write nothing to disk. The only local files in the
system are the two Qwen3 artefacts above, written exclusively by `local-indexer`
(`services/local-indexer/local_store.py`). No raw song dumps or caches are
written locally.

## gRPC surface (`proto/lirify.proto`)

| Call | Consumer | Cloud behaviour |
| --- | --- | --- |
| `Search`, `Recommend`, `GetTrack`, `ListTracks`, `GetLyrics`, `Stream` | astro SSR | served from the in-memory index + Qdrant |
| `GetIndexStats`, `WatchIndexStats`, `GetJob`, `GetFailedSongs`, `MatrixPreview` | go-webui / local-ui | read-only |
| `IndexPlaylist`, `QueuePlaylists`, `ExtractVideoIds`, `RetryFailed`, `IndexPlaylistFromBot` | local-ui, agents | `UNIMPLEMENTED` on Cloud Run |
| `LirifyIndexerService.PublishToCloud` | local-ui | not registered on Cloud Run |
| `LirifyIndexerService.GetLocalIndex` | local-ui | not registered on Cloud Run |

Triggering jobs and streaming progress intentionally reuse `LirifyService`, so
the local dashboard and the cloud services speak one contract. Only the two
laptop-only operations live in `LirifyIndexerService`.

The one-port decision is unchanged: Caddy on `:8080` routes
`application/grpc*` to `grpc.aio` (`:50051`) and everything else to uvicorn
(`:8000`). `grpc_server._abort()` sends initial metadata first so real status
codes survive Caddy's trailers-only handling.

## Recommendations without a user profile

1. The browser records plays in `localStorage`.
2. The home view sends up to five newest ids as seeds.
3. Astro forwards them to `Recommend` over gRPC.
4. python-backend averages Qdrant cosine neighbours across the seeds, excludes
   the seeds, and blends the title/artist Jaccard terms (`name .10 / artist .05`).
5. The `.85` lyrics term is the Qdrant similarity; without Qdrant the rebuilt
   in-process unified matrix answers instead (`engine: "matrix"`).

## Qwen3 tokenizer, Jaccard and the weighted matrix

The local indexer tokenises with the **exact** tokenizer of the embedding model
(`Qwen/Qwen3-Embedding-0.6B`, `tokenizer.json`). The tokenizer is used for:

1. **Vocabulary + full inverted index** (`local_store.rebuild`): subword terms →
   term ids → postings `{video_id: [positions]}`. Persisted only on the laptop.
2. **Index terms**: `main.lyrics_terms()` uses the Qwen3 subwords when available,
   so the in-memory TF-IDF matrix and the persisted artefacts describe the same
   terms. Without the assets (the cloud image), it falls back to the legacy
   whitespace/Snowball tokenizer.
3. **Title/artist Jaccard**: the only Jaccard signals. Terms come from
   `qwen_tokenizer.token_set()`; without the tokenizer they fall back to
   whitespace tokens.

```python
WEIGHTS = {"name": 0.10, "artist": 0.05, "lyrics": 0.85}
unified = .10 * jaccard(title terms)
        + .05 * jaccard(artist terms)
        + .85 * cosine(TF-IDF lyrics)
```

Jaccard is **not** computed for lyrics or language. Language is no longer a
similarity dimension, and no language is filtered out of the index.
`JACCARD_SCOPE = "name+artist"` is reported in stats so the dashboard can show
where the signal comes from.


## Indexing invariants (unchanged, now local-only)

- The index is accumulative: jobs add tracks, they never reset the library.
- A track is committed only with non-empty lyrics. **Any language is
  indexable**; language detection is metadata only and never gates a commit.
- `yt-dlp` extracts ids; two workers stage a stash (Atlas `stashes`) and commit it
  atomically under a lock.
- Duplicates are skipped per track; a batch is skipped only when nothing new is
  eligible.
- Failed lyric lookups are not cached; they land in `failed_songs` and are retried
  with bounded backoff.
- Terminal playlist failures are not retried on the server; agents resubmit after
  a jittered delay.
- Commits bump `index_stats.revision`; the cloud replica re-hydrates when it
  moves.
- A capped load never prunes.

## Embeddings

`local-indexer` calls `llama-server` at `LLAMA_EMBED_URL/v1/embeddings`
(OpenAI-compatible). The client batches `LLAMA_EMBED_BATCH` texts (default 8) and
truncates each to `LLAMA_EMBED_MAX_CHARS` (default 6000) so the conservative
`-c 2048` context is respected. If the model server is unavailable, the
deterministic hash embedding keeps indexing alive and logs a warning.

Qwen3-Embedding-0.6B produces **1024-dimensional** vectors. The stack uses
`lirify_lyrics_qwen3` with `QDRANT_VECTOR_SIZE=1024`; the old 256-dim
`lirify_lyrics` collection is intentionally left untouched. Switching back to
hash embeddings requires the old collection name and a reindex/publish.

## Free-tier capacity (cloud)

Cloud Run gives 2M requests, 360k GiB-s and 180k vCPU-s per month. The stack pins
`min_instances = 0`, `max_instances = 1`, `cpu = 1`, `cpu_idle = true`.

The serving replica still rebuilds TF-IDF and the `songs²` matrices from Atlas on
boot, so the memory guard remains: `MAX_INDEXED_SONGS` defaults to 3000 with
`python_memory = 1Gi`; a commit that would exceed it fails with
`Index capacity guard` rather than OOM-killing the revision. A capped load never
prunes. The Qwen3 Jaccard matrix is not built in the cloud image (no tokenizer
assets), so it adds no cloud memory.

## Cross-replica consistency

Atlas and Qdrant are the only sources of truth. Every local commit bumps
`index_stats.revision`; cloud instances compare it every
`INDEX_REFRESH_SECONDS` (default 60), and any inbound request also checks it at
most once per `INDEX_CHECK_SECONDS` (default 10) and schedules a re-hydrate.
`POST /admin/reload` (bot bearer) forces a synchronous reload. Cloud Run freezes
background work between requests, which is why the request-time check matters.

Reads keep the in-process per-IP limiter (`PUBLIC_RATE_LIMIT_PER_MINUTE`) on the
cloud serving replica. Writes are local-only, so `BOT_RATE_LIMIT` is now
relevant only when someone runs the full API with `SERVE_ONLY=false`.

## Known trade-offs

- **Two tokenizers.** The cloud image has no Qwen3 assets, so its matrix
  fallback uses the legacy tokenizer. Qdrant recommendations (the primary path)
  are unaffected because vectors are produced locally. Build the matrix with the
  same tokenizer only if you want the cloud fallback to match the laptop exactly
  (bake the tokenizer into the serving image and set
  `QWEN3_TOKENIZER_PATH`).
- **RTX 2050 4 GB.** Q8_0 weights (~0.65 GB) + `-c 2048` KV/compute buffers fit,
  but the compositor shares the GPU. Keep `-b/-ub 256`, `--parallel 1`; raise
  context only after checking `nvidia-smi`.
- **Jaccard cost.** Title/artist Jaccard is an `songs²` loop over short term
  sets; it is cheap and has no size cap. It is not applied to lyrics, so there
  is no `vocabulary × songs²` matmul any more.
- **Language labels.** `langdetect` labels are best-effort metadata (and Qdrant
  payload content); they do not affect ranking or eligibility.
- **Embedding dimension switch.** The new 1024-dim collection starts empty; run
  **Publish to cloud** once to backfill, and keep `QDRANT_COLLECTION` identical
  on the local indexer and the cloud API.
- `python-backend` is publicly invokable (read surface); the bot key now guards
  only `/admin/reload`. The local indexer is not exposed to the internet.
- Atlas allows `0.0.0.0/0` because Cloud Run egress IPs are dynamic. Use a strong
  password and rotate it via Secret Manager.
- Domain mappings remain free but provide no Cloud Armor.
