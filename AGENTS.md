# Lirify

Three-service lyrics index/player, deployed to Google Cloud Run. The Python
service is the only writer of index state (MongoDB Atlas + Qdrant Cloud); Go is
the admin UI; Astro is the end-user player. Both web UIs are stateless gRPC
clients and never touch a database.

Deep dives: `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`,
`docs/MONGODB_SCHEMA.md`, and the agent skill at
`skills/lirify-playlist-indexer/SKILL.md`.

## Run and verify

- `docker compose up -d --build` starts `mongo`, `qdrant`, `api` (8000 → REST +
  gRPC h2c behind the in-container mux), `go-ui` (8080), `web` (4321).
- Rebuild after edits: `docker compose build <service> && docker compose up -d <service>`.
  Go UI templates are embedded with `go:embed`, so template edits need a `go-ui` rebuild.
- Logs: `docker compose logs -f api`.
- Verify with:
  - `python3 -m py_compile services/api/app/*.py`
  - `cd services/go-ui && go build ./... && go vet ./...`
  - `cd services/web && npm run build`
  - `./scripts/gen_proto.sh --check` (fails if generated stubs drift)
- Smoke-test: `curl localhost:8000/health`, `/stats`, `/queue`, `/cache`,
  `/providers`, `/api/v1/bot/health`; then `curl localhost:8080/healthz` and
  `curl localhost:4321/healthz`.
- gRPC check: `grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats`.
- Index via the Go UI, `docker compose exec api python ws_client.py "<url>" index [limit]`,
  `POST /queue`, or the bot API (`POST /api/v1/bot/index-playlist`).
- Player dev: `cd services/web && npm run dev` (SSR; needs `GRPC_TARGET` and
  `PYTHON_BACKEND_URL`). `PUBLIC_API_BASE=http://HOST:8000` bypasses the SSR
  proxy for direct-to-API debugging.

## Architecture

- `proto/lirify.proto` is the single contract. `scripts/gen_proto.sh` generates
  Python, Go and TypeScript stubs into `services/api/app/lirifypb`,
  `services/go-ui/internal/lirifypb`, `services/web/src/generated`; all three are
  committed and CI drift-checks them. Never hand-edit generated files.
- `services/api/app/main.py` is the core monolith: committed `STATE` (an
  in-memory cache), lyric normalization, scraping, queue workers, TF-IDF/matrices,
  search, recommend, bot router and the legacy `/ws` stream.
- `services/api/app/store.py` is the **only** Mongo access layer (collections,
  validators, indexes). It falls back to `MemoryStore` when `MONGODB_URI` is unset
  (local dev only). No module may write to the container filesystem.
- `services/api/app/vector.py` is the only Qdrant access layer: deterministic
  hashed lyric embeddings, upsert/search/delete, `NullVectorStore` fallback.
- `services/api/app/grpc_server.py` serves `lirify.v1.LirifyService` over h2c on
  `GRPC_PORT` (50051). `Caddyfile` + `run.sh` mux one Cloud Run port: gRPC by
  content-type to grpc.aio, everything else to uvicorn. `_abort()` sends initial
  metadata first so gRPC status codes survive Caddy's trailers-only handling.
- `services/api/app/bot_api.py` is the bearer-protected `/api/v1/bot/*` router,
  including URL validation, rate limits, idempotency and error classification.
- `services/api/app/lyrics_sources.py` holds the 9-provider Limusic fallback chain.
  Add or reorder providers there, not in `main.py`.
- `services/api/app/player_api.py` is the additive, read-only `/api/player/*` router
  plus `preview_matrices` (shared with the gRPC `MatrixPreview` RPC). It persists
  only resolved durations (through `store.py`) and the in-memory playback session.
- `services/go-ui/{main,server,grpcclient,hub}.go` plus `templates/index.html`:
  JSON endpoints and SSE are adapted from gRPC; the hub holds one
  `WatchIndexStats` stream per instance and fans it out to browsers.
- `services/web` is the Astro SSR player (`src/lib`, `src/components`,
  `src/pages/index.astro`). `src/lib/grpc.ts` is server-only; `src/pages/api/player/[...path].ts`
  answers search/recommend/lyrics over gRPC and proxies the rest to python-backend.
- `scripts/` (except `gen_proto.sh`) is standalone coursework/experimentation and
  is not wired into the services or Docker images.
- `infra/` is the deployable stack; `infra/bootstrap/` creates the state bucket,
  Artifact Registry repo and Workload Identity Federation once, by hand.

## Indexing invariants

- The index is accumulative. `/index`, `/queue` and the bot API add to committed
  state; they never reset it.
- Two workers: `index_worker` scrapes and stores a stash in the Mongo `stashes`
  collection; `matrix_worker` computes matrices and commits the stash atomically.
- Only songs with non-empty lyrics **and** `language in {"en", "es"}` are
  committed. This filter is applied in `stage_index`, `stage_matrix`,
  `load_state`, and the failed-song retry worker.
- Language detection is `langdetect` plus an en/es hint fallback and a non-Latin
  script veto. Changing it changes what is eligible for the index.
- Duplicate handling is per song at commit. A batch is skipped only when it has
  zero new unique, eligible songs; partial duplicate batches still commit the new ones.
- Successful lyric lookups are cached in `lyrics_cache`; negative results are not
  cached, they go to `failed_songs` and are retried by the background worker.
- Pending jobs persist in `jobs`; failed jobs retry with backoff, except terminal
  playlist errors (`private_playlist`, `not_found`, `invalid_playlist`,
  `unavailable`, `restricted`, `geo_blocked`, `bot_check`). Tune with
  `MAX_JOB_ATTEMPTS` (default 8) and `RETRY_INTERVAL_SECONDS` (default 300).
- `MAX_INDEXED_SONGS` (default 1500) is a hard capacity guard for the 512 MiB
  container; exceeding it fails the batch instead of OOM-killing the revision.
- Similarity weights live only in `WEIGHTS` in `main.py`: name `.10`, artist
  `.05`, language `.05`, lyrics `.8`.

## Gotchas

- `data/` is legacy: the refactor removed every local JSON read/write. It is no
  longer mounted by `docker compose`. Do not reintroduce file I/O in the API.
- README and this file must stay in sync with `main.py`, `store.py` and the proto.
- `GET /song/{id}` and `/songs` expose only committed songs; filtered or
  not-yet-committed tracks return 404.
- `POST /extract` and the gRPC `ExtractVideoIds` only list ids; neither mutates the
  committed index. Use `/index`, `/queue` or the bot API to commit.
- `yt-dlp` is required at runtime in the API for playlist extraction, duration
  extraction, and the player stream proxy. YouTube periodically returns a bot
  challenge (`bot_check`); that is an egress problem, not a code bug.
- go-webui no longer has a WebSocket. The dashboard talks SSE
  (`/api/events`), fed by the gRPC stats watch stream. Update
  `templates/index.html` and `hub.go` together when adding events.
- Astro is now `output: "server"` (node adapter). Static-only assumptions
  (`npm run preview`) no longer apply; use `npm run build && npm start`.
- Free-tier deployment targets `us-central1`/`us-east1`, `min=0`, `max=1`.
  Raising `max_instances` or memory breaks the always-free assumption.
