# Lirify

A lyrics-first music index and player: scrape public YouTube playlists, resolve
lyrics, keep only English/Spanish tracks that actually have lyrics, and serve
similarity search, recommendations and synced lyrics.

Three stateless services on Google Cloud Run, backed by MongoDB Atlas and Qdrant
Cloud:

| Service | URL | Stack |
| --- | --- | --- |
| `astro-webui` | https://lirify.joscart.win | UPSpotify player, search, library and playlist import |
| `go-webui` | https://index.joscart.win | Legacy operator diagnostics (gRPC client) |
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

The running API never reads or writes the legacy `data/*.json` files. With the
local database overlay, `seed-catalogue` imports missing songs from the bundled
`data/songs.json` before the API starts. It only inserts missing IDs and never
overwrites existing songs or deletes a volume. To migrate other legacy data
into an explicitly configured database:

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
application user - idempotent, runs before the API), `seed-catalogue` (one-shot
local dataset import) and `qdrant`, plus `api`
(:8000 → REST + gRPC h2c, :50051 direct gRPC) and `web` (:4321). The legacy Go
dashboard is optional in the local overlay (`--profile legacy-admin`).

Local compose is deliberately unlimited so you can bulk-index while developing:
`MAX_INDEXED_SONGS=-1`, `PUBLIC_RATE_LIMIT_PER_MINUTE=0`, `BOT_RATE_LIMIT=0`.
Production flips all three to finite values (see `infra/variables.tf`).

Then:

- UPSpotify: http://localhost:4321 (search, playable catalogue, library and playlist import)
- Operator diagnostics: http://localhost:8081 (only with the `legacy-admin` or `public` profile)
- API docs: http://localhost:8000/docs

Rebuild after edits (images are not bind-mounted, so `up -d` alone keeps the old
code):

```bash
docker compose build api && docker compose up -d api
```

Go UI templates are embedded with `go:embed`, so template edits need a `go-ui`
rebuild.

### Local catalogue and lyrics

In PowerShell, from the repository root:

```powershell
docker compose -f docker-compose.yml -f docker-compose.local-db.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.local-db.yml logs seed-catalogue
(Invoke-RestMethod http://localhost:8000/stats).indexed_songs
```

Open the player and choose **Biblioteca** to browse or filter the songs by title
and artist. **Buscar** is the course search (TF-IDF/cosine on indexed lyrics).
**Agregar canciones** queues a public or unlisted playlist within the same UI.
The karaoke player uses the indexed LRC lyrics when available. For songs with
plain lyrics, the playback endpoint tries LRCLIB (`https://lrclib.net/api/search`)
and accepts matching title, artist, lyrics and compatible duration. Results are
cached for playback only; the ranking corpus is unchanged. If real timestamps
are unavailable, the app displays plain lyrics without inventing timing.

The same track row, buttons, navigation, typography and theme tokens are reused
across the search, catalogue and player. Dark navy with amber and light cream
with indigo preserve the existing UPSpotify identity. The lyric panel gives
the active verse the accent color, uses readable text for surrounding verses,
and scrolls only to follow real playback timestamps. Motion is functional and
respects reduced-motion preferences.

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
curl localhost:8081/health          # go-webui process
curl localhost:8081/readyz          # go-webui -> gRPC -> python-backend
curl localhost:4321/health          # astro-webui
curl -H "Authorization: Bearer $BOT_INGEST_API_KEY" localhost:8000/api/v1/bot/health
```

Verify gRPC end to end:

```bash
grpcurl -proto proto/lirify.proto -plaintext localhost:8000 \
  lirify.v1.LirifyService/GetIndexStats
```

## Indexing

All entry points share one queue and one commit path:

```bash
# UPSpotify (Add songs)
open http://localhost:4321/#/import

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

The player opens on **Search**. Enter a word or phrase from a song’s lyrics
and expand a result’s recommendations to see similar tracks.

To expand your local catalogue, open **Add songs**, paste a public or unlisted
YouTube playlist URL and select **Import playlist**. The import queue shows the
number of songs added. **Back to search** returns you to the player.

Both interfaces offer Español and English in the top bar. They remember the
selected language and pass it along when you switch between the two interfaces.

UPSpotify is the main lyrics search view. It ranks up to 10 songs by TF-IDF
cosine similarity and shows a short lyric excerpt for each match. Each result
has up to three recommendations calculated from the lyric cosine matrix.
Candidates include only songs outside the current top 10. The theme follows the
system preference on first visit and keeps the selected theme in the browser.

| Course material in 1P | Implementation |
| --- | --- |
| **3 · Ficheros invertidos**, pp. 24–26, 37 and 48 | Tokenization, stopwords, stemming and positional postings in `services/api/app/main.py`. The tokenizer folds vowel accents and preserves ñ. |
| **5 · Modelo Coseno Vectorial**, pp. 42–47 | Log-weighted TF, collection IDF, L2-normalized vectors and cosine ranking in `services/api/app/main.py` and `services/api/app/course_search.py`. Both the query and the lyrics use TF-IDF, as in the summary on p. 47. |
| **Proyecto 1**, pp. 1–2 | For each of the top 10 results, the app presents a lyric excerpt and up to three similar songs outside those 10 results. |

The HTTP route `GET /api/player/course-search?q=…` ranks the currently loaded
catalogue by cosine. Search ignores zero-score matches. An out-of-vocabulary
query, or a query made entirely of terms with zero IDF, returns an empty list.
Recommendations use the same lyric vectors. Each result includes up to three
eligible tracks, depending on the size of the corpus.

Run the unit tests from the repository root after installing the API requirements.

```powershell
$env:PYTHONPATH = (Resolve-Path 'services/api/app').Path
python -m unittest discover -s services/api/tests -v
```

The [Quality checks workflow](.github/workflows/quality.yml) also builds the Astro
app and exercises its search results, keyboard controls, mobile layout and themes
against a 14-song fixture. The deployment workflow calls these checks before
building or publishing images.

- Astro forwards UPSpotify search to the backend's HTTP route. Search
  suggestions, radio recommendations and lyrics use gRPC. The browser talks
  to the Astro origin.
- Listening history lives in `localStorage` and is the only source of
  recommendation seeds.
- Discover uses the browser's listening history to populate personalised shelves.

## Local ↔ cloud parity

Both stacks write to the same Atlas + Qdrant, so there is one dataset and each
process only holds a snapshot. `MAX_INDEXED_SONGS=-1` locally and `3000` in the
cloud means both serve the whole catalogue.

```bash
python3 scripts/sync_with_cloud.py parity      # local vs cloud counts
python3 scripts/sync_with_cloud.py index "<playlist url>"   # index locally, then reload cloud
python3 scripts/sync_with_cloud.py reload      # force cloud re-hydrate
```

Running instances also poll `index_stats.revision` every `INDEX_REFRESH_SECONDS`
(60s), so a batch committed locally appears in the cloud without any action.

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
