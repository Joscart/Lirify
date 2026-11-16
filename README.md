# Lirify

A lyrics-first music index and player: scrape public YouTube playlists, resolve
lyrics, keep only English/Spanish tracks that actually have lyrics, and serve
similarity search, recommendations and synced lyrics.

Three stateless services on Google Cloud Run, backed by MongoDB Atlas and Qdrant
Cloud:

| Service | URL | Stack |
| --- | --- | --- |
| `astro-webui` | https://lirify.joscart.win | Astro SSR player (gRPC client) |
| `go-webui` | https://index.liirify.joscart.win | Go indexer dashboard (gRPC client) |
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

The legacy `data/*.json` files are no longer read or written.

## Run

```bash
docker compose up -d --build
```

Brings up `mongo`, `qdrant`, `api` (:8000 → REST + gRPC h2c), `go-ui` (:8080) and
`web` (:4321). Then:

- Player: http://localhost:4321
- Indexer: http://localhost:8080
- API docs: http://localhost:8000/docs

Rebuild after edits:

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
accumulative; duplicates are skipped per track. Failed lookups go to
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
