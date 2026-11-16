# Lirify architecture

```
                    ┌─────────────────────────────┐
  browser ──HTTPS──▶│ astro-webui   (Cloud Run)   │
                    │  SSR /api/player/*          │
                    │  gRPC client ────────────┐  │
                    └──────────────────────────┘  │
                                                  │  gRPC / TLS :443 (h2c in)
  browser ──HTTPS──▶┌─────────────────────────────┐│
                    │ go-webui      (Cloud Run)   ││
                    │  gRPC client + SSE hub ───┐ ││
                    └──────────────────────────┘ ││
                                                 ▼▼
                    ┌──────────────────────────────────────────┐
  AI agent ──HTTPS──▶ python-backend (Cloud Run, one port)      │
   (bot API)        │  Caddy h2c mux                            │
                    │   ├─ content-type: application/grpc → grpc.aio :50051
                    │   └─ everything else               → uvicorn  :8000
                    │                                           │
                    │  MongoDB Atlas M0  ◀── only writer        │
                    │  Qdrant Cloud      ◀── only writer        │
                    └──────────────────────────────────────────┘
```

## Service boundaries

| Service | Owns | Never touches |
| --- | --- | --- |
| `python-backend` | MongoDB Atlas, Qdrant Cloud, yt-dlp, lyrics providers, all index mutations | the browser, local disk |
| `astro-webui` | SSR + the player UI; browser history | Mongo, Qdrant |
| `go-webui` | operator dashboard, SSE fan-out of the stats stream | Mongo, Qdrant, local disk |
| browser | listening history, search history, playback session | any database |

`python-backend` is the **only** process holding `MONGODB_URI`, `QDRANT_URL`,
`QDRANT_API_KEY` and `BOT_INGEST_API_KEY`. They arrive as Secret Manager
references; the two web UIs only know a gRPC target.

## Where state lives

| State | Home | Survives a cold start |
| --- | --- | --- |
| Committed tracks (title, artist, lyrics, language) | `songs` collection | yes |
| Lyric lookup cache (positive results only) | `lyrics_cache` | yes |
| Failed-song retry ledger | `failed_songs` | yes |
| Jobs + stashed batches | `jobs`, `stashes` | yes |
| Index statistics | `index_stats` | yes |
| Resolved media durations | `media_durations` | yes |
| Bot idempotency keys, rate-limit windows | `bot_idempotency`, `bot_rate_limits` | yes |
| Lyric embeddings (similarity) | Qdrant `lirify_lyrics` | yes |
| TF-IDF matrices, inverted index | process memory | no — rebuilt from Atlas on boot |
| Listening history, search history | browser `localStorage` | yes (per browser) |
| Playback clock, in-flight jobs | process memory | no — acceptable |

Nothing is written to the container filesystem. `docker compose` no longer mounts
`./data`; the old JSON files under `data/` are legacy and unused by this code.

## The one-port gRPC + REST decision

Cloud Run exposes a single container port, and there are two protocols to serve:

- gRPC from two web UIs (HTTP/2, `application/grpc`).
- JSON for the bot API, `/health`, `/stats` and the FastAPI `/docs`.

Serving them from one Python process is not possible without re-implementing
HTTP/2 routing, so the image runs a three-process mux:

1. **Caddy** on `:8080` accepts inbound h2c (Cloud Run is configured with
   `ports { name = "h2c" }`, i.e. `--use-http2` end to end).
2. `Content-Type: application/grpc*` → Caddy `reverse_proxy` over h2c to
   `grpc.aio` on `127.0.0.1:50051`.
3. Everything else → `uvicorn` on `127.0.0.1:8000`.

Caddy drops **trailers-only** gRPC responses (an error status carried in the
initial HEADERS frame); clients see `UNKNOWN`. `grpc_server._abort()` therefore
sends initial metadata first, which forces a normal response plus trailers, so
real status codes (`NOT_FOUND`, `INVALID_ARGUMENT`, …) survive the mux. This is
verified against a live container in `grpc_server.py` and the runbook.

Alternative considered: two Cloud Run services (one gRPC, one REST). Rejected
because it doubles the always-free surface and splits the bot API from the index
it writes to.

## gRPC surface (`proto/lirify.proto`)

| Call | Consumer | Notes |
| --- | --- | --- |
| `Search` | astro SSR | TF-IDF + name/artist boost, unchanged ranking |
| `Recommend` | astro SSR | browser-supplied seeds; Qdrant neighbours, matrix fallback |
| `GetTrack`, `ListTracks`, `GetLyrics`, `Stream` | astro SSR | shaping stays server-side |
| `IndexPlaylist`, `QueuePlaylists`, `ExtractVideoIds` | go-webui | URL-validated, returns a `Job` |
| `GetJob`, `GetIndexStats`, `WatchIndexStats` | go-webui | the watch stream drives browser SSE |
| `GetFailedSongs`, `RetryFailed`, `MatrixPreview` | go-webui | admin views |
| `IndexPlaylistFromBot` | agents (gRPC path) | mirrors the HTTP bot endpoint |

`search` and `recommendations` are the two calls that expose ranking logic, so the
Astro layer answers them over gRPC. The rest of the player surface (catalogue
shaping, byte-range video proxy, playback session) is proxied server-side by the
same Astro route: the browser still only talks to one origin, and no database
driver exists in the web image.

## Recommendations without a user profile

1. The browser records plays in `localStorage` (`src/lib/history.ts`).
2. On the home view it sends up to five newest ids as `seeds` to
   `/api/player/radio/{seed}?seeds=…`.
3. Astro forwards them to `Recommend` over gRPC.
4. python-backend averages Qdrant cosine neighbours across the seeds, excludes the
   seeds themselves, and blends the same weights as the matrix
   (`lyrics 0.8 / name 0.10 / artist 0.05 / lang 0.05`).
5. With no Qdrant configured, the rebuilt in-process unified matrix answers
   instead (`engine: "matrix"` in the response).

A first-time browser has no history, so `hasOnboarded()` is false and the home
view renders the search gate instead of fetching personalised shelves.

## Indexing invariants (unchanged)

- The index is accumulative: jobs add tracks, they never reset the library.
- A track is committed only with non-empty lyrics **and**
  `language in {en, es}`.
- `yt-dlp` extracts ids; two workers stage a stash (Mongo `stashes`) and commit
  it atomically under a lock.
- Duplicates are skipped per track; a batch is skipped only when nothing new is
  eligible.
- Failed lyric lookups are not cached; they land in `failed_songs` and are retried
  with bounded backoff.
- Terminal playlist failures (private, deleted, malformed, geo-blocked, bot check)
  are **not** retried — that would burn free-tier quota on guaranteed failures.

## Free-tier capacity

Cloud Run gives 2M requests, 360k GiB-s and 180k vCPU-s per month. The stack
pins `min_instances = 0`, `max_instances = 1`, `cpu = 1`, `cpu_idle = true`.

The binding constraint is memory: 512 MiB must hold the TF-IDF matrix
(`vocabulary × songs` float32) and up to five `songs²` float32 matrices. At
N = 1500 that is roughly 45 MB of matrices plus the vocabulary; `MAX_INDEXED_SONGS`
defaults to 1500 and the matrix worker refuses to commit beyond it with a clear
error instead of being OOM-killed mid-batch.

## Known trade-offs

- `python-backend` is publicly invokable because the bot API must be reachable and
  the web UIs do not mint Google ID tokens. Read endpoints expose the public lyric
  index; every write requires `BOT_INGEST_API_KEY`. Set `python_public = false` and
  add ID-token auth if you need a private backend.
- Atlas allows `0.0.0.0/0` because Cloud Run egress IPs are dynamic on the free
  tier. Use a strong password and rotate it via Secret Manager.
- Domain mappings are used instead of a load balancer: free, but they need Search
  Console domain verification and do not provide Cloud Armor.
- The playback clock and in-flight job progress are in memory; both are cosmetic
  and rebuildable.
