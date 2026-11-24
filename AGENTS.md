# Lirify

Lyrics index/player split into two stacks that share one contract:

- **Cloud serving (read-only, three Cloud Run services):** `python-backend`
  (`SERVE_ONLY=true`), `go-webui` (`DASHBOARD_MODE=readonly`) and `astro-webui`.
  They serve committed state and never scrape, embed or write index state.
- **Local indexing (laptop, RTX 2050 4 GB):** `local-indexer` (same Python code,
  `SERVE_ONLY=false`), `local-ui` (same Go dashboard, `DASHBOARD_MODE=local`) and
  `llama.cpp` serving Qwen3-Embedding-0.6B. Only the laptop writes Atlas/Qdrant.

Deep dives: `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`,
`docs/MONGODB_SCHEMA.md`, and the agent skill at
`skills/lirify-playlist-indexer/SKILL.md` (its HTTP path is retired; see banner).

## Run and verify

- Serving stack: `docker compose up -d --build` starts `api`, `web`, `go-ui`
  against `MONGODB_URI`/`QDRANT_URL` from `.env` (Atlas + Qdrant Cloud here).
  `api` runs `SERVE_ONLY=true`: index routes answer `403`, indexing RPCs
  `UNIMPLEMENTED`, and only the revision poller runs.
- Containerised databases:
  `docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build`
  adds `mongo`, `db-init`, `qdrant`.
- Local indexing stack:
  `docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml up -d --build llama local-indexer local-ui`
  (ports: `local-ui` 8090, `local-indexer` 50052→50051, `llama` 8081→8080).
  Model + tokenizer: `scripts/local/fetch_qwen3_embedding.sh`.
- Local compose runs unlimited on purpose: `MAX_INDEXED_SONGS=-1`,
  `PUBLIC_RATE_LIMIT_PER_MINUTE=0`, `BOT_RATE_LIMIT=0`. Production uses 3000 /
  120/min / 30 per hour.
- Rebuild after edits: `docker compose build <service> && docker compose up -d <service>`.
  Go UI templates are embedded with `go:embed`, so template edits need a rebuild.
  The local-indexer image builds from the repository root:
  `docker build -f services/local-indexer/Dockerfile .`
- Logs: `docker compose logs -f api` / `... logs -f local-indexer`.
- Verify with:
  - `python3 -m py_compile services/api/app/*.py services/local-indexer/*.py`
  - `cd services/go-ui && go build ./... && go vet ./...`
  - `cd services/web && npm run build`
  - `./scripts/gen_proto.sh --check` (fails if generated stubs drift)
- Smoke-test: `curl localhost:8000/health` (`mode=serve-only`), `/stats`,
  `/queue`, `/cache`, `/providers`, `/api/v1/bot/health`; `POST /index` → 403;
  then `curl localhost:8080/health`/`readyz`, `curl localhost:4321/health`.
- gRPC check: `grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats`; local indexer on `localhost:50052`
  also exposes `lirify.v1.LirifyIndexerService/GetLocalIndex`.
- Index via `local-ui` (8090) or gRPC:
  `grpcurl -proto proto/lirify.proto -plaintext localhost:50052 -d
  '{"playlist_urls":["<url>"]}' lirify.v1.LirifyService/QueuePlaylists`.
  `POST /queue` works only on an API you run with `SERVE_ONLY=false`; the cloud
  bot API is intentionally unavailable. The local-indexer has no HTTP surface.
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
- `services/api/app/main.py` is the core monolith: committed `STATE`, lyric
  normalization, scraping, queue workers, TF-IDF/matrices, search, recommend,
  bot router and the legacy `/ws` stream. `SERVE_ONLY` disables every mutation
  and worker except the revision poller.
- `services/api/app/qwen_tokenizer.py` loads the exact
  `Qwen/Qwen3-Embedding-0.6B` tokenizer (`QWEN3_TOKENIZER_PATH` or HF) and
  degrades to the legacy whitespace/stem tokenizer when the assets are absent
  (the cloud image).
- `services/api/app/store.py` is the **only** Mongo access layer. When
  `SERVE_ONLY=true` it refuses every index write (`ReadOnlyStoreError`); only
  `duration_put` (player metadata) is allowed. No module writes the container
  filesystem.
- `services/api/app/vector.py` is the only Qdrant access layer: llama.cpp
  `/v1/embeddings` when `LLAMA_EMBED_URL` is set, deterministic hash fallback
  otherwise, upsert/search/delete, `NullVectorStore` fallback. When
  `SERVE_ONLY=true` it never creates a collection or upserts.
- `services/api/app/grpc_server.py` serves `lirify.v1.LirifyService` over h2c on
  `GRPC_PORT` (50051) from the FastAPI startup hook (`GRPC_INPROCESS`). Indexing
  RPCs abort with `UNIMPLEMENTED` when `SERVE_ONLY=true`. `Caddyfile` + `run.sh`
  mux one Cloud Run port; `_abort()` sends initial metadata first so status codes
  survive Caddy's trailers-only handling.
- `services/local-indexer/local_server.py` is the gRPC-only writer entrypoint:
  registers both services, starts the workers, and hooks
  `local_store.rebuild` after every commit. `local_store.py` is the only local
  disk writer: `vocabulary.json` + `inverted_index.json` (atomic, Qwen3 terms).
- `services/api/app/bot_api.py` is the bearer-protected `/api/v1/bot/*` router,
  mounted only when `SERVE_ONLY=false`.
- `services/api/app/lyrics_sources.py` holds the 9-provider Limusic fallback chain.
  Add or reorder providers there, not in `main.py`.
- `services/api/app/player_api.py` is the additive, read-only `/api/player/*`
  router plus `preview_matrices`; it persists only resolved durations and the
  in-memory playback session.
- `services/go-ui/{main,server,grpcclient,hub}.go` plus `templates/index.html`:
  JSON endpoints and SSE adapted from gRPC. `DASHBOARD_MODE=readonly` hides the
  controls, answers `403` on write routes and never registers the indexer stub in
  practice; `local` adds `/api/publish` and `/api/local-index`.
- `services/web` is the Astro SSR player. `src/lib/grpc.ts` is server-only;
  `src/pages/api/player/[...path].ts` answers search/recommend/lyrics over gRPC
  and proxies read-only endpoints to python-backend.
- `scripts/` (except `gen_proto.sh` and `scripts/local/`) is standalone
  coursework/experimentation and is not wired into the services.
- `infra/` is the deployable stack; `infra/bootstrap/` creates the state bucket,
  Artifact Registry repo and Workload Identity Federation once, by hand.

## Indexing invariants

- Only `local-indexer` (`SERVE_ONLY=false`) indexes. The index is accumulative:
  jobs add tracks, they never reset the library.
- Two workers: `index_worker` scrapes and stores a stash in the Mongo `stashes`
  collection; `matrix_worker` computes matrices and commits the stash atomically.
- Only songs with non-empty lyrics are committed. **Any language is indexable**;
  this rule is applied in `stage_index`, `stage_matrix`, `load_state`, and the
  failed-song retry worker.
- Language detection (`langdetect` best effort) is metadata only and never
  gates a commit.
- Duplicate handling is per song at commit. A batch is skipped only when it has
  zero new unique, eligible songs; partial duplicate batches still commit the new ones.
- Successful lyric lookups are cached in `lyrics_cache`; negative results are not
  cached, they go to `failed_songs` and are retried by the background worker.
- Pending jobs persist in `jobs`. Playlist scrape failures never retry on the
  server: the job ends in `error`/`gave_up` with a classified `error_code` and a
  `retry_mode`. `MAX_JOB_ATTEMPTS` (8) and `RETRY_INTERVAL_SECONDS` (300) bound
  matrix-commit and failed-song retries only.
- `MAX_INDEXED_SONGS` (default 3000 with `python_memory = 1Gi`) bounds
  `load_state` and commits (`Index capacity guard`). `-1` disables it locally.
  Measured peak RSS: 1000 songs ≈ 227 MB, 1661 ≈ 401 MB.
- **Never prune from a capped load.** A replica that hydrates a subset must not
  delete rows it did not read. `prune_songs` is explicit, never a boot side effect.
- Every commit bumps `index_stats.revision`. Cloud instances check it on inbound
  requests (`INDEX_CHECK_SECONDS`, 10) and via a 60 s poller, then re-hydrate.
  `POST /admin/reload` (bot bearer) forces it.
- Embeddings: llama.cpp Qwen3-Embedding-0.6B, 1024 dims, collection
  `lirify_lyrics_qwen3`. The client batches 8 and truncates to 6000 chars
  (`LLAMA_EMBED_*`); hash fallback keeps indexing alive if llama is down.
- Similarity weights live only in `WEIGHTS` in `main.py`: name `.10`, artist
  `.05`, lyrics `.85`. Jaccard is **only** used for title/artist (Qwen3 subword
  sets when available); lyrics is TF-IDF cosine. Language is not a similarity
  dimension and there is no language allow-list. `JACCARD_SCOPE = "name+artist"`
  is reported in stats.
- The public REST surface is rate limited per IP on the serving replica; the bot
  write path (only with `SERVE_ONLY=false`) is limited per API key in Mongo.

## Gotchas

- `SERVE_ONLY` defaults to **true**. Forgetting it yields a serving replica that
  cannot mutate the index (safe); set it to `0` only for `local-indexer`.
- Two tokenizers exist: Qwen3 subwords (laptop, with assets) and the legacy
  whitespace/Snowball tokenizer (cloud image). Qdrant recommendations are
  unaffected; only the in-process matrix fallback differs. See
  `docs/ARCHITECTURE.md`.
- Switching embedding dimension requires a **new Qdrant collection name**
  (`QDRANT_COLLECTION`) on both stacks and a **Publish to cloud** backfill.
  Never point 1024-dim vectors at the old 256-dim `lirify_lyrics`.
- Only two local files are allowed: `local-index/vocabulary.json` and
  `local-index/inverted_index.json`. Do not add song dumps or local caches.
- `data/` is legacy and unmounted. Do not reintroduce file I/O in the cloud API.
- MongoDB is configured by **connection string only**: `MONGODB_URI` (alias
  `MONGO_URI`) for the API, `MONGO_ROOT_URI` for `db-init`. The DB name comes from
  the URI path when `MONGODB_DB` is unset. `infra/mongo/init.js` parses
  `MONGODB_URI`.
- Atlas users live in `admin`: `MONGODB_URI` needs `authSource=admin`.
- Legacy JSON can be loaded with `scripts/migrate_json_to_mongo.py` (run it
  against the configured database from the laptop, not from the serving image).
- GitHub environment variables/secrets are invisible to jobs that do not declare
  the environment. All config-consuming jobs declare `Lirify`; check with
  `scripts/setup-github.sh --check`.
- After editing Python code, `docker compose up -d api` is not enough: run
  `docker compose build api && docker compose up -d api` (or the local-indexer
  equivalent).
- README and this file must stay in sync with `main.py`, `store.py`,
  `vector.py`, `local_store.py` and the proto.
- `GET /song/{id}` and `/songs` expose only committed songs.
- `yt-dlp` is required at runtime for playlist extraction, durations, and the
  player stream proxy. YouTube bot challenges are an egress problem, not a bug.
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
