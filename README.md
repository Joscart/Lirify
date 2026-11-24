# Lirify

A lyrics-first music index and player. Public YouTube playlists are scraped,
lyrics are resolved, tracks with lyrics are kept (any language), and the result
powers similarity search, recommendations and synced lyrics.

Lirify is two stacks sharing one gRPC contract and one pair of databases:

| Stack | Services | Role |
| --- | --- | --- |
| **Cloud serving** (read-only) | `astro-webui`, `go-webui`, `python-backend` (`SERVE_ONLY=true`) | Search, recommend, lyrics, player, stats. Never scrapes, embeds or writes index state. |
| **Local indexing** (laptop, RTX 2050 4 GB) | `llama.cpp` + `local-indexer` + `local-ui` | Full pipeline, Qwen3-Embedding-0.6B embeddings, Atlas/Qdrant writes, local vocabulary + inverted index. |

| Service | URL | Stack |
| --- | --- | --- |
| `astro-webui` | https://lirify.joscart.win | Astro SSR player (gRPC client) |
| `go-webui` | https://index.joscart.win | Go stats/health dashboard (`DASHBOARD_MODE=readonly`) |
| `python-backend` | Cloud Run, private URL | FastAPI + gRPC (h2c), read-only serving |
| `local-ui` | http://localhost:8090 | Same Go dashboard with index/publish controls |
| `local-indexer` | gRPC `:50052` → `:50051` | Writer: pipeline + llama.cpp embeddings |
| `llama-server` | http://localhost:8081 | Qwen3-Embedding-0.6B (GGUF, CUDA) |

- **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Deployment runbook:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- **Database schema:** [`docs/MONGODB_SCHEMA.md`](docs/MONGODB_SCHEMA.md)
- **Agent skill:** [`skills/lirify-playlist-indexer/SKILL.md`](skills/lirify-playlist-indexer/SKILL.md) (retired HTTP path; see its banner)

## Contract first

Every service boundary is defined once in [`proto/lirify.proto`](proto/lirify.proto)
and generated into Python, Go and TypeScript:

```bash
./scripts/gen_proto.sh          # regenerate all three
./scripts/gen_proto.sh --check  # CI: fail on drift
```

Generated code is committed (`services/api/app/lirifypb`,
`services/go-ui/internal/lirifypb`, `services/web/src/generated`) so builds stay
reproducible and offline-friendly. Never hand-edit it.

`LirifyService` carries both read and index RPCs, so the local dashboard and the
cloud services speak one contract. `LirifyIndexerService` adds the two
laptop-only operations: `PublishToCloud` and `GetLocalIndex`.

## Stateless serving, local writes

Cloud Run may recycle a container at any time, so the cloud containers write
nothing to disk. The laptop indexer is the only writer:

| State | Owner |
| --- | --- |
| Tracks, jobs, stashes, caches, stats, `revision` | MongoDB Atlas (`local-indexer` writes) |
| Qwen3 lyric embeddings (1024-dim) | Qdrant Cloud `lirify_lyrics_qwen3` (`local-indexer` writes) |
| Qwen3 vocabulary | `local-index/vocabulary.json` (laptop only) |
| Full inverted index (term id → postings) | `local-index/inverted_index.json` (laptop only) |
| TF-IDF matrices | process memory, rebuilt from Atlas on boot |
| Listening/search history, playback session | the browser (`localStorage`) |

No song dumps or local caches are written; the two files above are the only local
artefacts. The legacy `data/*.json` files are unused.

## Run the cloud serving stack locally

```bash
cp .env.example .env      # already present in this checkout

# Cloud databases (Atlas + Qdrant Cloud) — what .env points at today:
docker compose up -d --build

# or containerised databases, no cloud account:
docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build
```

The serving stack is `api`, `web` and `go-ui` only; the `local-db` overlay adds
`mongo`, `db-init` and `qdrant`. `api` runs with `SERVE_ONLY=true`: `/index`,
`/queue`, `/extract`, `/retry` and the bot ingestion routes answer `403`, every
indexing gRPC RPC answers `UNIMPLEMENTED`, and only the revision poller runs.

- Player: http://localhost:4321
- Read-only dashboard: http://localhost:8080
- API docs: http://localhost:8000/docs

## Run the local indexing stack (laptop)

Download the model + tokenizer once (Q8_0, ~0.65 GB):

```bash
scripts/local/fetch_qwen3_embedding.sh
```

Then, with `nvidia-smi` working inside Docker:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml \
  up -d --build llama local-indexer local-ui

# containerised databases + local indexer (no Atlas/Qdrant Cloud):
docker compose -f docker-compose.yml -f docker-compose.local-db.yml \
  -f docker-compose.local-indexer.yml up -d --build llama local-indexer local-ui
```

- Dashboard with controls: http://localhost:8090
- llama.cpp embeddings: http://localhost:8081 (`/v1/embeddings`)
- Indexing gRPC: `localhost:50052`

The overlay sets `SERVE_ONLY=0`, `LLAMA_EMBED_URL=http://llama:8080`,
`QWEN3_TOKENIZER_PATH=/models/qwen3-embedding/tokenizer.json`,
`QDRANT_COLLECTION=lirify_lyrics_qwen3`, `QDRANT_VECTOR_SIZE=1024` and
`LOCAL_INDEX_DIR=/data/local-index`. Index a playlist from the dashboard, then
use **Publish to cloud** for a first backfill or after switching collections.

### llama.cpp budget for the RTX 2050

The compose service runs:

```
--embedding --pooling last --ctx-size 2048 --batch-size 256 --ubatch-size 256 \
--parallel 1 --n-gpu-layers 99
```

Q8_0 weights (~0.65 GB) plus KV/compute buffers fit in 4 GB next to the
compositor. Check `nvidia-smi` during the first run; raise `-c`/`-b` only with
headroom. `LLAMA_EMBED_BATCH=8` and `LLAMA_EMBED_MAX_CHARS=6000` bound the
client side. `Q4_K_M` is the fallback if another workload occupies VRAM.

## Embeddings, tokens and similarity

- Text is embedded by llama.cpp with **Qwen3-Embedding-0.6B** (1024 dims).
- The exact `Qwen/Qwen3-Embedding-0.6B` tokenizer builds the local vocabulary,
  the full inverted index, and the term sets used by title/artist Jaccard.
- `WEIGHTS = {"name": 0.10, "artist": 0.05, "lyrics": 0.85}`. Jaccard is used
  **only** for the title and artist signals; lyrics is TF-IDF cosine. Language is
  not a similarity dimension, and no language is filtered out of the index.

```
unified = .10 * jaccard(title terms)
        + .05 * jaccard(artist terms)
        + .85 * cosine(TF-IDF lyrics)
```

The unified matrix is peak-normalised. Title/artist Jaccard uses Qwen3 subword
sets when the tokenizer is loaded and falls back to whitespace tokens otherwise.

## Verify

```bash
./scripts/gen_proto.sh --check
python3 -m py_compile services/api/app/*.py services/local-indexer/*.py
(cd services/go-ui && go build ./... && go vet ./...)
(cd services/web && npm run build)
```

Smoke test:

```bash
curl localhost:8000/health          # mode=serve-only
curl localhost:8000/stats           # serve_only: true
curl -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/index \
  -H 'Content-Type: application/json' -d '{"url":"https://youtu.be/xxxxxxxxxxx"}'   # 403
curl localhost:8080/health          # go-webui process + mode
curl localhost:8080/readyz          # go-webui -> gRPC -> python-backend
curl localhost:4321/health          # astro-webui
curl -H "Authorization: Bearer $BOT_INGEST_API_KEY" localhost:8000/api/v1/bot/health
```

gRPC end to end:

```bash
grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats

# local indexer (both services on one port)
grpcurl -proto proto/lirify.proto -plaintext localhost:50052 \
  lirify.v1.LirifyIndexerService/GetLocalIndex
```

## Indexing entry points (local only)

```bash
# Dashboard
open http://localhost:8090

# gRPC (grpcurl on the host; the local-indexer has no HTTP surface)
grpcurl -proto proto/lirify.proto -plaintext \
  -d '{"playlist_urls":["https://www.youtube.com/playlist?list=..."],"source":"local-ui"}' \
  localhost:50052 lirify.v1.LirifyService/QueuePlaylists

# HTTP (only when you run the API yourself with SERVE_ONLY=false)
curl -X POST localhost:8000/queue -H 'Content-Type: application/json' \
  -d '{"urls": ["https://www.youtube.com/playlist?list=..."]}'
```

Commit rules: non-empty lyrics. Any language is indexable. The index is
accumulative; duplicates are skipped per track. Failed lookups go to
`failed_songs` and are retried with bounded backoff. Terminal playlist errors are
not retried on the server.

## Local ↔ cloud parity

Both stacks read the same Atlas + Qdrant; only the laptop writes. Every commit
bumps `index_stats.revision`; cloud instances compare it every
`INDEX_REFRESH_SECONDS` (60 s) and on inbound requests at most every
`INDEX_CHECK_SECONDS` (10 s), so a local batch becomes visible without a
redeploy.

```bash
python3 scripts/sync_with_cloud.py parity   # local vs cloud counts
python3 scripts/sync_with_cloud.py reload   # force cloud re-hydrate
```

## Deployment

Push to `main`. GitHub Actions verifies the contract and builds (`verify`),
pushes three images to Artifact Registry (`images`), applies Terraform against a
GCS remote state bucket (`deploy`), and smoke-tests the `*.run.app` URLs
(`smoke`). The three Cloud Run services are read-only; no Cloud Run service can
index. One-time GCP, Atlas, Qdrant, DNS and GitHub setup is in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Python API surface

| Route | Cloud serving | Local indexer (`SERVE_ONLY=false`) |
| --- | --- | --- |
| `GET /health`, `/stats`, `/queue`, `/cache`, `/providers`, `/matrices` | read-only | read-only |
| `POST /extract`, `/index`, `/queue`, `/retry` | `403` | indexing |
| `GET /search`, `/recommend/{id}`, `/songs`, `/song/{id}` | yes | yes |
| `GET/POST /api/player/*` | yes (duration persistence allowed) | yes |
| `/api/v1/bot/*` | health only; writes `403` | bearer-protected ingestion |
| `/ws` | status/ping only | live progress |
| gRPC `LirifyService` | player + read RPCs; index RPCs `UNIMPLEMENTED` | full |
| gRPC `LirifyIndexerService` | not registered | publish + local index |

## Notes

- `yt-dlp` is required at runtime for playlist extraction, duration extraction and
  the player stream proxy.
- `GET /song/{id}` and `/songs` expose only committed songs.
- Similarity weights live only in `WEIGHTS` in `services/api/app/main.py`.
- `SERVE_ONLY` defaults to **true** (safe): forgetting the flag on a deployment
  yields a serving replica that cannot mutate the index.
- `store.py` and `vector.py` refuse writes when `SERVE_ONLY=true`; `duration_put`
  (player metadata) is the one explicitly allowed write.
- Go UI templates are embedded with `go:embed`: rebuild `go-ui` after template
  edits.
