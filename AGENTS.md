# Lirify

Lyrics index/player split into two independent stacks that share one gRPC
contract:

- **Cloud serving (read-only, three Cloud Run services):** `python-backend`,
  `go-webui` (`DASHBOARD_MODE=readonly`) and `astro-webui`. They serve committed
  songs and pre-computed LLM embeddings. No scraping, no embeddings, no matrices,
  no index writes.
- **Local indexing (standalone, laptop):** `local-indexer` (ingestion + `core.py`
  + sentence-transformers Qwen3-Embedding-0.6B + Atlas/Qdrant writes) and
  `local-ui` (the same Go dashboard, `DASHBOARD_MODE=local`). It never calls the
  cloud API, and the cloud API never calls it.

Deep dives: `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`,
`docs/MONGODB_SCHEMA.md`, and the agent skill at
`skills/lirify-playlist-indexer/SKILL.md` (its HTTP path is retired; see banner).

## Run and verify

- Serving stack: `docker compose up -d --build` starts `api`, `web`, `go-ui`
  against `MONGODB_URI`/`QDRANT_URL` from `.env` (Atlas + Qdrant Cloud here).
  `api` is read-only: index routes answer `403`, indexing RPCs `UNIMPLEMENTED`.
- Containerised databases:
  `docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build`
  adds `mongo`, `db-init`, `qdrant`.
- Local indexer stack:
  `docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml up -d --build local-indexer local-ui`
  (ports: `local-ui` 8090, `local-indexer` 50052→50051). No llama.cpp service:
  `core.py` embeds with sentence-transformers inside `local-indexer`.
- First local-indexer start downloads `Qwen/Qwen3-Embedding-0.6B` into the
  `hf_cache` volume. Rebuilds after edits:
  `docker compose build local-indexer && docker compose up -d local-indexer`.
  The image builds from the repository root (it needs the generated gRPC stubs):
  `docker build -f services/local-indexer/Dockerfile .`
- Web search uses Cloudflare Workers AI. Configure `CF_WORKER_URL`, or
  `CF_ACCOUNT_ID` + `CF_API_TOKEN`, plus optional `CF_AI_MODEL`; unset falls back
  to lexical search.
- Logs: `docker compose logs -f api` / `... logs -f local-indexer`.
- Verify with:
  - `python3 -m py_compile services/api/app/*.py services/local-indexer/*.py`
  - `cd services/local-indexer && python3 -m unittest discover -s tests -p 'test_*.py'`
  - `cd services/go-ui && go build ./... && go vet ./...`
  - `cd services/web && npm run build`
  - `./scripts/gen_proto.sh --check` (fails if generated stubs drift)
- Smoke-test: `curl localhost:8000/health` (`mode=serve-only`), `/stats`,
  `/queue`, `/cache`, `/api/v1/bot/health`; `POST /index` → 403; then
  `curl localhost:8080/api/stats`, `curl localhost:8080/api/tracks`,
  `curl localhost:4321/health`.
- gRPC check: `grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats`; local indexer on `localhost:50052`
  also exposes `lirify.v1.LirifyIndexerService/GetLocalIndex`.
- Index via `local-ui` (8090) or gRPC:
  `grpcurl -proto proto/lirify.proto -plaintext localhost:50052 -d
  '{"playlist_urls":["<url>"]}' lirify.v1.LirifyService/QueuePlaylists`.
  The local-indexer has no HTTP surface.
- Player dev: `cd services/web && npm run dev` (SSR; needs `GRPC_TARGET` and
  `PYTHON_BACKEND_URL`). `PUBLIC_API_BASE=http://HOST:8000` bypasses the SSR
  proxy for direct-to-API debugging.

## Architecture

- `proto/lirify.proto` is the single contract. `scripts/gen_proto.sh` generates
  Python, Go and TypeScript stubs into `services/api/app/lirifypb`,
  `services/go-ui/internal/lirifypb`, `services/web/src/generated`; all three are
  committed and CI drift-checks them. Never hand-edit generated files.
  `LirifyService` carries read + index RPCs; `LirifyIndexerService` adds
  `PublishToCloud` and `GetLocalIndex` for the laptop only.
- `services/local-indexer/core.py` is **the engine**: text pipeline (one flat
  term list), inverted index, TF-IDF matrices, `SentenceTransformer`, `buscar()`,
  `recomendar()`, `estadisticas()` and `publicar()`. Tests:
  `services/local-indexer/tests/test_core.py` (offline, fake encoder).
- `services/local-indexer/ingest.py` is the only scraper (`yt-dlp`, noembed,
  langdetect); `lyrics_sources.py` holds the 9-provider Limusic chain. Add or
  reorder providers there.
- `services/local-indexer/pipeline.py` serialises playlists, keeps jobs in
  memory and calls `core.Indexer` → `core.publicar`. `local_server.py` is the
  gRPC entrypoint for `local-ui`; it registers both services.
- `services/api/app/main.py` is now a small read-only server: committed `STATE`
  from Atlas, lexical `search`, Qdrant `recommend_songs`, stats and the player
  router. It builds no matrices and imports no ingestion code.
- `services/api/app/store.py` is the **only** Mongo access layer. When
  `SERVE_ONLY=true` it refuses every index write; only `duration_put` (player
  metadata) is allowed.
- `services/api/app/vector.py` is the only Qdrant access layer and it is
  read-only in the cloud: `neighbours()` for recommendations, `NullVectorStore`
  fallback. It never creates the collection or upserts.
- `services/api/app/grpc_server.py` serves `lirify.v1.LirifyService` over h2c on
  `GRPC_PORT` from the FastAPI startup hook (`GRPC_INPROCESS`). Indexing RPCs
  abort with `UNIMPLEMENTED`. `Caddyfile` + `run.sh` mux one Cloud Run port.
- `services/api/app/player_api.py` is the additive, read-only `/api/player/*`
  router; it persists only resolved durations and the playback session. It
  tolerates `state["matrices"]` being empty (the cloud has no matrices).
- `services/go-ui/{main,server,grpcclient,hub}.go` plus `templates/index.html`:
  JSON endpoints and SSE adapted from gRPC. `DASHBOARD_MODE=readonly` hides the
  controls and answers `403` on write routes; `local` adds `/api/publish` and
  `/api/local-index`. `/api/tracks` lists every committed track.
- `services/web` is the Astro SSR player. `src/lib/grpc.ts` is server-only;
  `src/lib/cloudflare.ts` expands search queries with Workers AI;
  `src/lib/search-ai.ts` merges the per-keyword gRPC searches.
  `src/pages/api/player/[...path].ts` answers search/recommend/lyrics and proxies
  read-only endpoints to python-backend.
- `scripts/` (except `gen_proto.sh` and `scripts/local/`) is standalone
  coursework/experimentation and is not wired into the services.
- `infra/` is the deployable stack; `infra/bootstrap/` creates the state bucket,
  Artifact Registry repo and Workload Identity Federation once, by hand.

## Indexing invariants

- Only `local-indexer` indexes. The index is accumulative: playlists add tracks;
  the library is never reset.
- Only songs with non-empty lyrics are committed. **Any language is indexable**;
  language detection is metadata only and unsupported languages fall back to a
  generic tokenizer instead of being dropped.
- Duplicates are skipped per `video_id` inside `core.indexar_canciones`.
- `core.publicar()` writes songs to Atlas and LLM embeddings to Qdrant, then bumps
  `index_stats.revision`. It is the only cloud write path.
- No matrices are published. `index_stats.build` carries counts and embedding
  metadata only.
- `PUBLISH_ON_INDEX=1` publishes after each committed playlist;
  `LOCAL_INDEX_DIR` is no longer used (there are no local index files).
- `LOAD_ON_START=1` hydrates the in-memory index from Atlas so restarts keep the
  library and duplicate detection intact.
- **Never prune from a capped load.** A replica that hydrates a subset must not
  delete rows it did not read.
- Cloud instances compare `index_stats.revision` on inbound requests
  (`INDEX_CHECK_SECONDS`, 10) and via the 60 s poller, then re-read songs.
  `POST /admin/reload` forces it.
- Embeddings: sentence-transformers `Qwen/Qwen3-Embedding-0.6B`, 1024 dims,
  collection `lirify_lyrics_qwen3`.
- Similarity weights in the cloud live in `main.WEIGHTS`: name `.10`, artist
  `.05`, lyrics `.85`. Jaccard is **only** title/artist; lyrics is Qdrant
  similarity. Language is not a similarity dimension and there is no allow-list.
- The public REST surface is rate limited per IP
  (`PUBLIC_RATE_LIMIT_PER_MINUTE`; 0 disables it).

## Gotchas

- Indexing routes in the cloud are gone by design: `/index`, `/queue`,
  `/extract`, `/retry` return `403` and the bot router is not mounted.
- Switching embedding dimension requires a **new Qdrant collection name**
  (`QDRANT_COLLECTION`) plus a publish backfill. Never point 1024-dim vectors at
  the old 256-dim `lirify_lyrics`.
- `local_indexer` is GPU-heavy on first run (torch + model download). Keep the
  `hf_cache` volume; deleting it forces a full re-download.
- `data/` is legacy and unmounted. Do not reintroduce file I/O in the cloud API.
- `services/api/app/qwen_tokenizer.py` is no longer imported by any service; it is
  kept only because it carries uncommitted user edits.
- MongoDB is configured by **connection string only**: `MONGODB_URI` (alias
  `MONGO_URI`) for the API, `MONGO_ROOT_URI` for `db-init`. The DB name comes from
  the URI path when `MONGODB_DB` is unset.
- Atlas users live in `admin`: `MONGODB_URI` needs `authSource=admin`.
- GitHub environment variables/secrets are invisible to jobs that do not declare
  the environment. All config-consuming jobs declare `Lirify`; check with
  `scripts/setup-github.sh --check`.
- After editing Python code, `docker compose up -d api` is not enough: run
  `docker compose build api && docker compose up -d api` (or the local-indexer
  equivalent).
- README and this file must stay in sync with `core.py`, `pipeline.py`,
  `main.py`, `store.py`, `vector.py` and the proto.
- `GET /song/{id}` and `/songs` expose only committed songs.
- `yt-dlp` is required at runtime for playlist extraction (local-indexer) and the
  player stream proxy (python-backend). YouTube bot challenges are an egress
  problem, not a bug.
- go-webui has no WebSocket: SSE `/api/events` is fed by the gRPC stats watch.
  Update `templates/index.html` and `hub.go` together.
- Astro is `output: "server"` (node adapter); use `npm run build && npm start`.
- Cloud Run reserves `PORT` (`K_*`/`CLOUD_RUN_*`): never declare them in
  `infra/main.tf`. Images default to 8080.
- Terraform state has a GCS lock: do not `terraform apply` locally during a CI
  deploy (`Error 412 ... tflock`).
- The index host is `index.joscart.win` (direct child of the verified apex).
  Domain mappings need owner verification and **DNS only** Cloudflare records.
- The `*.run.app` edge intercepts `/healthz`; use `/health` publicly (`go-webui`
  keeps `/healthz` for container-local probes) and `/readyz`.
- Free tier: `us-central1`/`us-east1`, `min=0`, `max=1`. Raising either breaks
  the always-free assumption.
- YouTube anti-bot challenges are terminal for the server by design; retries are
  agent-driven and jittered, and one large playlist beats many small ones.
- `skills/lirify-playlist-indexer` documents the retired Cloud Run bot API; use
  the local dashboard or local gRPC instead.
