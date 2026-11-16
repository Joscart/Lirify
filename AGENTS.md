# Lirify

Three-service lyrics index/player, deployed to Google Cloud Run. The Python
service is the only writer of index state (MongoDB Atlas + Qdrant Cloud); Go is
the admin UI; Astro is the end-user player. Both web UIs are stateless gRPC
clients and never touch a database.

Deep dives: `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`,
`docs/MONGODB_SCHEMA.md`, and the agent skill at
`skills/lirify-playlist-indexer/SKILL.md`.

## Run and verify

- `docker compose up -d --build` starts `api`, `web` and `go-ui` against whatever
  `MONGODB_URI`/`QDRANT_URL` point at (Atlas + Qdrant Cloud in this checkout).
  For containerised databases add the overlay:
  `docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build`
  which also starts `mongo`, `db-init`, `qdrant` and `api`
  (8000 → REST + gRPC h2c behind the in-container mux, 50051 direct gRPC),
  `go-ui` (8080), `web` (4321). Configuration comes from `.env` (copy
  `.env.example`); `db-init` creates the database + app user before the API boots.
- Local compose runs unlimited on purpose: `MAX_INDEXED_SONGS=-1`,
  `PUBLIC_RATE_LIMIT_PER_MINUTE=0`, `BOT_RATE_LIMIT=0`. Production uses 1000 /
  120/min / 30 per hour.
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
- Pending jobs persist in `jobs`. **Playlist scrape failures never retry on the
  server**: the job ends in `error`/`gave_up` with a classified `error_code` and a
  `retry_mode` (`agent-jitter` or `never`). Agents resubmit through the bot API
  after a randomised delay. `MAX_JOB_ATTEMPTS` (default 8) and
  `RETRY_INTERVAL_SECONDS` (default 300) now bound matrix-commit retries and
  failed-song lyric retries only.
- `MAX_INDEXED_SONGS` (default 1000) bounds both sides: `load_state` hydrates
  only the newest N songs, and a commit that would exceed N fails with
  `Index capacity guard` instead of OOM-killing the revision. `-1` disables it
  (local compose only). Measured peak RSS after the in-place TF-IDF rewrite:
  1000 songs ≈ 227 MB, 1661 ≈ 401 MB — the old implementation needed 504 MB for
  1000 and could not boot on Cloud Run.
- The public REST surface is rate limited per IP (`PUBLIC_RATE_LIMIT_PER_MINUTE`,
  in-process limiter in `main.py`); the bot write path is limited per API key via
  MongoDB so the quota survives cold starts. Both accept `0` = unlimited.
- Similarity weights live only in `WEIGHTS` in `main.py`: name `.10`, artist
  `.05`, language `.05`, lyrics `.8`.

## Gotchas

- `data/` is legacy: the refactor removed every local JSON read/write. It is no
  longer mounted by `docker compose`. Do not reintroduce file I/O in the API.
- MongoDB is configured by a **connection string only**: `MONGODB_URI` (alias
  `MONGO_URI`) for the API, `MONGO_ROOT_URI` for the one-shot `db-init`. The
  database name is derived from the URI path when `MONGODB_DB` is unset.
  `infra/mongo/init.js` parses `MONGODB_URI` to create the app user, so there are
  no duplicated credential variables.
- Atlas database users live in the `admin` auth database: `MONGODB_URI` must carry
  `authSource=admin`, otherwise the driver fails with `bad auth : Authentication
  failed`. `infra/mongo/init.js` cannot create users there (Atlas-managed) and is
  expected to continue with a warning.
- Legacy JSON can be loaded into the configured database with
  `scripts/migrate_json_to_mongo.py` (idempotent upserts, matrices excluded).
- GitHub-wise: variables/secrets on an *environment* are invisible to jobs that
  do not declare it. All configuration-consuming jobs declare
  `Lirify` (override with a repository variable `DEPLOY_ENVIRONMENT`).
  A preflight failure that lists every variable/secret is a level mismatch, not
  an empty config — check with `scripts/setup-github.sh --check`.
- After editing Python code, `docker compose up -d api` is not enough: run
  `docker compose build api && docker compose up -d api` (images are not mounted).
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
- Cloud Run reserves `PORT` (and the `K_*`/`CLOUD_RUN_*` names): never declare
  them in `infra/main.tf`. The images default to 8080 and read the injected value.
- Free-tier deployment targets `us-central1`/`us-east1`, `min=0`, `max=1`.
  Raising `max_instances` or memory breaks the always-free assumption.
- YouTube anti-bot challenges are terminal for the server by design; retries are
  agent-driven (`skills/lirify-playlist-indexer`), jittered, and should submit one
  large playlist rather than many small ones.
