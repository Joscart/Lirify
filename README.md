# Lirify

A lyrics-first music index and player. Public YouTube playlists are scraped,
lyrics are resolved, tracks with lyrics are kept (any language), and the result
powers search, recommendations and synced lyrics.

Lirify is two independent stacks sharing one gRPC contract and one pair of
databases:

| Stack | Services | Role |
| --- | --- | --- |
| **Cloud serving** (read-only) | `astro-webui`, `go-webui`, `python-backend` | Serve committed songs + pre-computed LLM embeddings. No scraping, no embeddings, no matrices, no index writes. |
| **Local indexing** (laptop) | `local-indexer` + `local-ui` | `core.py` pipeline: scrape → terms → Qwen3-Embedding-0.6B → Atlas + Qdrant. |

| Service | URL | Stack |
| --- | --- | --- |
| `astro-webui` | https://lirify.joscart.win | Astro SSR player; Cloudflare Workers AI search, gRPC recommendations |
| `go-webui` | https://index.joscart.win | Read-only dashboard (`DASHBOARD_MODE=readonly`) |
| `python-backend` | Cloud Run, private URL | FastAPI + gRPC (h2c), read-only serving |
| `local-ui` | http://localhost:8090 | Same Go dashboard with index/publish controls |
| `local-indexer` | gRPC `:50052` → `:50051` | Ingestion, `core.py`, sentence-transformers embeddings, cloud writes |

- **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Deployment runbook:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- **Database schema:** [`docs/MONGODB_SCHEMA.md`](docs/MONGODB_SCHEMA.md)

## Contract first

Every service boundary is defined once in [`proto/lirify.proto`](proto/lirify.proto)
and generated into Python, Go and TypeScript:

```bash
./scripts/gen_proto.sh          # regenerate all three
./scripts/gen_proto.sh --check  # CI: fail on drift
```

Generated code is committed (`services/api/app/lirifypb`,
`services/go-ui/internal/lirifypb`, `services/web/src/generated`). Never
hand-edit it.

`LirifyService` carries read + index RPCs, so the local dashboard and the cloud
services speak one contract. `LirifyIndexerService` adds `PublishToCloud` and
`GetLocalIndex` and is registered only by `local-indexer`.

## `core.py` is the engine

`services/local-indexer/core.py` owns the whole index: text pipeline, terms,
inverted index, TF-IDF matrices (memory only), Qwen3 embeddings, `buscar()`,
`recomendar()`, `estadisticas()` and `publicar()`. The cloud API has no copy of
that logic; it reads the published state.

Database ownership:

| State | Home | Writer |
| --- | --- | --- |
| Tracks (title, artist, lyrics, language) | Atlas `songs` | `local-indexer` |
| Index statistics + `revision` | Atlas `index_stats` | `local-indexer` |
| Resolved media durations | Atlas `media_durations` | `python-backend` (player metadata) |
| Qwen3-Embedding-0.6B vectors (1024-dim) | Qdrant `lirify_lyrics_qwen3` | `local-indexer` |
| Terms, TF-IDF, similarity matrices | local process memory | `core.py` |
| Listening/search history | browser `localStorage` | browser |

Only songs and LLM embeddings are published. No matrices reach the cloud and no
container writes to disk.

## Recommendations and web search

- **Recommendations** use the pre-computed embeddings only: Qdrant cosine
  neighbours per seed, blended with `.10` title / `.05` artist Jaccard
  (`.85` lyrics). Weights live in `python-backend` (`main.WEIGHTS`).
- **Web search** is understood by Cloudflare Workers AI: Astro asks the Worker
  (or the Workers AI REST API) for 1–3 catalogue keywords, then runs one gRPC
  `Search` per keyword and merges by score. Configure `CF_WORKER_URL`, or
  `CF_ACCOUNT_ID` + `CF_API_TOKEN`; without them the route falls back to lexical
  search.

## Run the cloud serving stack locally

```bash
cp .env.example .env      # already present in this checkout

# Cloud databases (Atlas + Qdrant Cloud) — what .env points at today:
docker compose up -d --build

# or containerised databases, no cloud account:
docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build
```

- Player: http://localhost:4321
- Read-only dashboard: http://localhost:8080
- API docs: http://localhost:8000/docs

`api` is read-only: `/index`, `/queue`, `/extract`, `/retry` and the bot routes
answer `403`; indexing gRPC RPCs answer `UNIMPLEMENTED`.

## Run the standalone local indexer

The first start downloads `Qwen/Qwen3-Embedding-0.6B` into the `hf_cache` volume
(~1.2 GB, cached afterwards).

```bash
docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml \
  up -d --build local-indexer local-ui

# Dashboard with controls: http://localhost:8090
# Indexing gRPC:            localhost:50052
```

The indexer reads `MONGODB_URI`, `QDRANT_URL` and `QDRANT_API_KEY` from `.env`,
hydrates committed songs from Atlas at startup, and publishes after every
committed playlist (`PUBLISH_ON_INDEX=1`). Publish again from the dashboard to
backfill a new embedding collection.

## Verify

```bash
./scripts/gen_proto.sh --check
python3 -m py_compile services/api/app/*.py services/local-indexer/*.py
(cd services/local-indexer && python3 -m unittest discover -s tests -p 'test_*.py')
(cd services/go-ui && go build ./... && go vet ./...)
(cd services/web && npm run build)
```

Smoke test:

```bash
curl localhost:8000/health          # liveness; mode=serve-only, revision
curl localhost:8000/readyz          # readiness: Atlas hydrated (503 until ready)
curl localhost:8000/stats           # serve_only: true, vectors: qdrant
curl -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/index \
  -H 'Content-Type: application/json' -d '{"url":"https://youtu.be/xxxxxxxxxxx"}'   # 403
curl localhost:8080/api/stats       # go-webui JSON
curl localhost:8080/api/tracks      # every committed track
curl localhost:4321/health          # astro-webui
```

gRPC end to end:

```bash
grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats

grpcurl -proto proto/lirify.proto -plaintext localhost:50052 \
  lirify.v1.LirifyIndexerService/GetLocalIndex
```

## Index a playlist (local only)

```bash
grpcurl -proto proto/lirify.proto -plaintext localhost:50052 \
  -d '{"playlist_urls":["<url>"]}' lirify.v1.LirifyService/QueuePlaylists
```

The local-indexer has no HTTP surface. The dashboard is the supported UI, and
ingestion uses `yt-dlp` plus the nine-provider lyric chain.
