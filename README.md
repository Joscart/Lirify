# Lirify

A lyrics-first music index and player: scrape public YouTube playlists, resolve
lyrics, keep only English/Spanish tracks that actually have lyrics, and serve
similarity search, recommendations and synced lyrics.

Three stateless services on Google Cloud Run, backed by MongoDB Atlas and Qdrant
Cloud:

| Service | URL | Stack |
| --- | --- | --- |
| `astro-webui` | https://lirify.joscart.win | Astro SSR player (gRPC client) |
| `go-webui` | https://index.lirify.joscart.win | Go indexer dashboard (gRPC client) |
| `python-backend` | Cloud Run, private URL | FastAPI + gRPC (h2c) core engine |
| AI agents | `POST /api/v1/bot/index-playlist` | bearer-protected ingestion API |

- **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Deployment runbook:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- **Database schema:** [`docs/MONGODB_SCHEMA.md`](docs/MONGODB_SCHEMA.md)
- **Agent skill:** [`skills/lirify-playlist-indexer/SKILL.md`](skills/lirify-playlist-indexer/SKILL.md)

## Contract first

Every service boundary is defined once in [`proto/lirify.proto`](proto/lirify.proto)
and generated into Python, Go and TypeScript:

```bash
./scripts/gen_proto.sh          # regenerate all three
./scripts/gen_proto.sh --check  # CI: fail on drift
```

Generated code is committed (`services/api/app/lirifypb`,
`services/go-ui/internal/lirifypb`, `services/web/src/generated`) so builds stay
reproducible and offline-friendly.

## Stateless by design

Cloud Run may recycle a container at any time, so nothing is written to disk:

| State | Owner |
| --- | --- |
| Tracks, jobs, stashes, caches, stats | MongoDB Atlas (`python-backend` only) |
| Lyric embeddings | Qdrant Cloud (`python-backend` only) |
| Listening/search history, playback session | the browser (`localStorage`) |
| TF-IDF matrices, inverted index | process memory, rebuilt from Atlas on boot |

The legacy `data/*.json` files are no longer read or written. To move an existing
on-disk library into the configured database:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/scripts:/scripts:ro" -v "$PWD/data:/legacy:ro" \
  api python /scripts/migrate_json_to_mongo.py --data-dir /legacy
docker compose restart api   # rebuilds the index and backfills Qdrant
```

## Run

```bash
cp .env.example .env      # already present in this checkout

# Cloud databases (Atlas + Qdrant Cloud) — what .env points at today:
docker compose up -d --build

# or containerised databases, no cloud account:
docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build
```

MongoDB is configured with **connection strings only**: `MONGODB_URI` is the single
source of truth (the API connects with it verbatim, and `db-init` parses it to
create the database and application user). `MONGO_ROOT_URI` exists solely for that
one-shot init step. Point `MONGODB_URI` at an Atlas string to leave the container
behind.

The default stack is `api`, `web` and `go-ui` only; the `local-db` overlay adds
`mongo` (root-authenticated), `db-init` (creates the `lirify` database and its
application user — idempotent, runs before the API) and `qdrant`, plus `api`
(:8000 → REST + gRPC h2c, :50051 direct gRPC), `go-ui` (:8080) and `web` (:4321).

Local compose is deliberately unlimited so you can bulk-index while developing:
`MAX_INDEXED_SONGS=-1`, `PUBLIC_RATE_LIMIT_PER_MINUTE=0`, `BOT_RATE_LIMIT=0`.
Production flips all three to finite values (see `infra/variables.tf`).

Then:

- Player: http://localhost:4321
- Indexer: http://localhost:8080
- API docs: http://localhost:8000/docs

Rebuild after edits (images are not bind-mounted, so `up -d` alone keeps the old
code):

```bash
docker compose build api && docker compose up -d api
```

Go UI templates are embedded with `go:embed`, so template edits need a `go-ui`
rebuild.

## Verify

```bash
python3 -m py_compile services/api/app/*.py
(cd services/go-ui && go build ./... && go vet ./...)
(cd services/web && npm run build)
./scripts/gen_proto.sh --check
```

Smoke test the stack:

```bash
curl localhost:8000/health          # {"storage":{"tracks":"mongodb","vectors":"qdrant"}}
curl localhost:8000/stats
curl localhost:8080/healthz         # go-webui -> gRPC -> python-backend
curl localhost:4321/healthz         # astro-webui
curl -H "Authorization: Bearer $BOT_INGEST_API_KEY" localhost:8000/api/v1/bot/health
```

Verify gRPC end to end:

```bash
grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats
```

## Indexing

All three entry points share one queue and one commit path:

```bash
# Operator (dashboard)
open http://localhost:8080

# Script
docker compose exec api python ws_client.py "<playlist-url>" index 50

# HTTP
curl -X POST localhost:8000/queue -H 'Content-Type: application/json' \
  -d '{"urls": ["https://www.youtube.com/playlist?list=..."]}'

# AI agent (HTTP, bearer)
curl -X POST localhost:8000/api/v1/bot/index-playlist \
  -H "Authorization: Bearer $BOT_INGEST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"playlist_url": "https://www.youtube.com/playlist?list=...", "source_bot": "my-agent"}'
```

Commit rules: non-empty lyrics **and** `language in {en, es}`. The index is
accumulative; duplicates are skipped per track. `MAX_INDEXED_SONGS` defaults to
1000 in production (512 MiB container) and is `-1` (unlimited) in local compose. Failed lookups go to
`failed_songs` and are retried with bounded backoff. Terminal playlist errors
(private, deleted, malformed, geo-blocked, YouTube bot check) are not retried.

## Player behaviour

- Search and recommendations are answered by `python-backend` over gRPC from the
  Astro SSR layer; the browser never sees the API host.
- Listening history lives in `localStorage` and is the only source of
  recommendation seeds.
- A first visit renders an onboarding gate: one search is required before
  personalised shelves are fetched.

## Deployment

Push to `main`. GitHub Actions verifies the contract and builds
(`verify`), pushes three images to Artifact Registry (`images`), applies Terraform
against a GCS remote state bucket (`deploy`), and smoke-tests the
`*.run.app` URLs (`smoke`).

One-time GCP, Atlas, Qdrant, DNS and GitHub setup is documented step by step in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Terraform lives in `infra/`
(services, secrets, domain mappings) and `infra/bootstrap/` (state bucket,
Artifact Registry, Workload Identity Federation).

## Python API surface

| Route | Purpose |
| --- | --- |
| `GET /health`, `/stats`, `/queue`, `/cache`, `/providers` | Operations |
| `POST /extract`, `/index`, `/queue`, `/retry` | Indexing |
| `GET /search`, `/recommend/{id}`, `/songs`, `/song/{id}` | Search |
| `GET/POST /api/player/*` | Player shaping, lyrics, stream proxy, session |
| `POST /api/v1/bot/index-playlist` | Bot ingestion (bearer) |
| `GET /api/v1/bot/jobs/{job_id}` | Bot job polling (bearer) |
| `/ws` | Legacy live-progress WebSocket (local tooling) |
| gRPC `lirify.v1.LirifyService` | All machine-to-machine traffic |

## Notes

- `yt-dlp` is required at runtime for playlist extraction, duration extraction and
  the player stream proxy.
- `GET /song/{id}` and `/songs` expose only committed songs.
- `POST /extract` only lists ids; it does not mutate the index.
- Similarity weights live only in `WEIGHTS` in `services/api/app/main.py`
  (`name .10`, `artist .05`, `lang .05`, `lyrics .8`).
