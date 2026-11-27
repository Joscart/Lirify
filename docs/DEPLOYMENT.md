# Lirify deployment runbook

Everything in this file is the **manual** part of the pipeline. Code, Terraform and
CI are in the repository; the steps below create the accounts and identities that
CI cannot create for itself.

Work top to bottom. Steps 1–6 are one-time. Steps 7–9 are the first deploy; step
10 is the laptop indexing stack.

> **Two independent stacks, one contract.** Cloud Run hosts only the three
> read-only serving services (`python-backend`, `astro-webui`, `go-webui` with
> `DASHBOARD_MODE=readonly`). Indexing, embedding and publishing run in the
> standalone laptop `local-indexer` (+ `local-ui`), which is the only writer of
> Atlas/Qdrant. See `docs/ARCHITECTURE.md`.


> **Domains.** Both hosts are direct children of the verified apex: `lirify.joscart.win`
> (player) and `index.joscart.win` (indexer). Do not use `index.lirify.joscart.win`
> (a sub-subdomain): it needs separate validation and has repeatedly failed
> certificate provisioning, so the mapping was moved to `index.joscart.win`.
>
> `lirify.joscart.win` and `index.joscart.win`
> (indexer) are the defaults in `infra/variables.tf`, `docker-compose.yml` and
> `.env.example`. If you deploy to different hosts, change the GitHub variables
> (`WEB_DOMAIN`, `INDEX_DOMAIN`) and the matching `TF_VAR_*` values together — a
> hostname you cannot verify will block certificate issuance.

---

## 0. What you need

- A GCP account with billing enabled (the Always Free tier still requires a
  billing account; no charges accrue inside the limits used here).
- A GitHub repository containing this project (CI runs from `main`).
- A MongoDB Atlas account (free M0 cluster).
- A Qdrant Cloud account (free tier cluster).
- DNS control for `joscart.win`.
- Local tools: `gcloud`, `terraform` ≥ 1.6, `docker` (only for local testing).

---

## 1. Create the GCP project

1. Create the project and select it:

   ```bash
   gcloud config set project lirify-514907
   ```

   (Project `lirify-514907` already exists in this deployment; the bootstrap
   outputs are recorded in `infra/BOOTSTRAP.md`.)

2. Link billing (required for Cloud Run and Artifact Registry):

   ```bash
   gcloud billing accounts list
   gcloud billing projects link lirify-prod \
     --billing-account=XXXXXX-XXXXXX-XXXXXX
   ```

3. Authenticate Terraform as a project owner (bootstrap only):

   ```bash
   gcloud auth application-default login
   ```

> **Free-tier guardrails** you get from `infra/`: `us-central1`, Cloud Run
> `min_instances = 0`, `max_instances = 1` per service, `cpu = 1`,
> `memory = 1Gi` (python) / `512Mi` (web) / `256Mi` (go), request-based billing
> (`cpu_idle = true`), Artifact Registry pruning to two versions per image, and a
> `MAX_INDEXED_SONGS` capacity guard (default 1000) so a 512 MiB container is never OOM-killed.

---

## 2. Bootstrap the GCP identities and repositories

This creates the state bucket, the Artifact Registry repository, the Workload
Identity Federation pool and the deploy service account.

```bash
cd infra/bootstrap
terraform init
terraform apply \
  -var project_id=lirify-prod \
  -var region=us-central1 \
  -var github_repository=YOUR_GH_OWNER/lirify
```

Record the three outputs — they become GitHub repository variables in step 6:

```bash
terraform output state_bucket                  # -> TF_STATE_BUCKET
terraform output workload_identity_provider    # -> GCP_WORKLOAD_IDENTITY_PROVIDER
terraform output deploy_service_account        # -> GCP_DEPLOY_SERVICE_ACCOUNT
```

Keep `infra/bootstrap/terraform.tfstate` somewhere safe (it is git-ignored). It
holds the only record of these identities.

---

## 3. Create the MongoDB Atlas M0 cluster

1. Sign in at <https://cloud.mongodb.com> → **Create** → **M0 Free**.
2. Provider/region: **AWS**, a region close to `us-central1` (e.g. `us-east-1`).
   Qdrant and Atlas do not need to match the Cloud Run region, but lower latency
   helps cold starts.
3. **Database Access** → add a user, e.g. `lirify` with *Read and write to any
   database*. Save the password.
4. **Network Access** → add `0.0.0.0/0`.

   Cloud Run egress IPs are not static on the free tier, so an IP allowlist is not
   practical. The database user password is the security boundary — use a long
   generated password and keep it only in GitHub Secrets and Atlas.
5. **Connect → Drivers** → copy the `mongodb+srv://...` string, substitute the
   password, and append the database name:

   ```
   mongodb+srv://lirify:PASSWORD@cluster0.xxxxx.mongodb.net/lirify?retryWrites=true&w=majority
   ```

6. Collections and indexes are created automatically by `python-backend` on first
   boot (`store.ensure_schema`). No manual seeding is needed.

---

## 4. Create the Qdrant Cloud cluster

1. Sign in at <https://cloud.qdrant.io> → **Create cluster** → **Free** tier.
2. Pick a region (any is fine; `eu-central` or `us-east` keeps latency sane).
3. Copy the **cluster URL** — it looks like
   `https://xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.eu-central.aws.cloud.qdrant.io:6333`.
   Keep the `:6333` port: the REST API is what the backend uses.
4. Create an **API key** for the cluster and copy it.
5. Nothing else to configure: `local-indexer` creates the
   `lirify_lyrics_qwen3` collection (1024-dim, cosine) on first publish, and
   backfills vectors for existing tracks. Keep `QDRANT_COLLECTION` identical on
   the laptop and on Cloud Run; the old 256-dim `lirify_lyrics` collection is not
   reused (an embedding-dimension change needs a new collection name).

---

## 5. Generate the bot API key

```bash
openssl rand -hex 32
```

This value is the bearer token AI agents use. It is stored in Secret Manager as
`lirify-bot-ingest-api-key` and injected only into `python-backend`.

---

## 6. Configure the GitHub repository

**Settings → Secrets and variables → Actions.**

> **Where to store them.** Every job that reads configuration declares
> `environment: ${{ vars.DEPLOY_ENVIRONMENT || 'Lirify' }}`. That means
> repository-level and `production`-environment-level values both work — but only
> the level you chose. The classic symptom of a mismatch is a preflight failure
> listing **all** variables and secrets as missing. Choose one and stay there:
> `scripts/setup-github.sh` (repository level) or
> `scripts/setup-github.sh --env Lirify` (environment level).
> `scripts/setup-github.sh --check [--env Lirify]` shows what exists where.

### Repository variables (non-secret)

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `lirify-prod` |
| `GCP_REGION` | `us-central1` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | output from step 2 |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | output from step 2 |
| `TF_STATE_BUCKET` | output from step 2 |
| ~~`WEB_DOMAIN`~~ / ~~`INDEX_DOMAIN`~~ | no longer used: the domains are defined in `infra/variables.tf` so a stale variable cannot rename (and destroy) a domain mapping. Delete them if present. |
| `ENABLE_DOMAIN_MAPPINGS` | `false` until step 9 is done, then `true` |
| `GCP_PROJECT_ID` | `lirify-514907` |

### Repository secrets

| Secret | Value |
| --- | --- |
| `MONGODB_URI` | Atlas connection string from step 3 |
| `QDRANT_URL` | Qdrant cluster URL from step 4 |
| `QDRANT_API_KEY` | Qdrant API key from step 4 |
| `BOT_INGEST_API_KEY` | token from step 5 |
Optionally create a `production` environment (Settings → Environments) and add
required reviewers if you want manual approval on deploys.

> The bot key no longer enables indexing on Cloud Run: there is no ingestion
> router in the serving image. `/admin/reload` is unauthenticated and only
> re-reads committed songs after a local publish.

### Workflow permissions

The workflow needs no PAT: it authenticates with OIDC
(`permissions: id-token: write`) against the Workload Identity pool created in
step 2, constrained to `assertion.repository == "<owner>/<repo>"`.

---

## 7. First deployment

1. Commit and push to `main`. The workflow runs four jobs in order:
   1. `verify` — regenerates Python/Go/TypeScript stubs and fails on drift, runs
      `py_compile`, `go build`/`go vet` and the Astro SSR build.
   2. `images` — builds and pushes three images to Artifact Registry.
   3. `deploy` — `terraform init` (GCS state) → `plan` → `apply`. All three Cloud
      Run services are created in one apply.
   4. `smoke` — polls `/health` (python), `/healthz` (web) and `/healthz` (index)
      on the `*.run.app` URLs.
2. Watch it: **Actions → Deploy Lirify to Cloud Run**.
3. If `deploy` fails on the first run because the Cloud Run API was just enabled,
   re-run the job once.

Grab the service URLs from the job summary, or:

```bash
gcloud run services list --region us-central1
```

At this point everything works on `*.run.app` URLs, including gRPC. Custom
domains come next.

---

## 8. Verify the API directly

```bash
API=$(gcloud run services describe lirify-api --region us-central1 --format='value(status.url)')

curl -s "$API/health"                       # liveness: {"status":"ok","mode":"serve-only",...}
curl -s -w '\n%{http_code}\n' "$API/readyz" # readiness: store + gRPC + index (503 until ready)
curl -s "$API/stats" | head -c 400          # revision, weights, vectors store
curl -s "$API/api/v1/bot/health" -H "Authorization: Bearer $BOT_INGEST_API_KEY"

# The serving replica must refuse writes:
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API/index" \
  -H 'Content-Type: application/json' -d '{"url":"https://youtu.be/xxxxxxxxxxx"}'
# 403

# gRPC over TLS :443 (the same path the web UIs use)
grpcurl -proto proto/lirify.proto \
  -H "x-lirify-client: runbook" \
  "$(echo "$API" | sed 's|https://||'):443" lirify.v1.LirifyService/GetIndexStats

# The indexing RPC is UNIMPLEMENTED on Cloud Run:
grpcurl -proto proto/lirify.proto -d '{"playlist_url":"https://youtu.be/xxxxxxxxxxx"}' \
  "$(echo "$API" | sed 's|https://||'):443" lirify.v1.LirifyService/IndexPlaylist
```

If `grpcurl` returns `Unknown` for an error response, confirm the service is the
one built from this repository: `python-backend` sends initial metadata before
aborting so gRPC status codes survive the in-container h2c mux.

---

## 9. Custom domains and managed certificates

`joscart.win` is registered at Cloudflare (`bob.ns.cloudflare.com`,
`maleah.ns.cloudflare.com`) but currently publishes **no records**, so nothing
resolves yet. Domain mappings also require the domain to be **verified** by an
owner of the GCP project; without that the Terraform apply fails.

Order matters:

1. **Create the zone.** Cloudflare dashboard → Add site → `joscart.win` → keep the
   assigned nameservers. The zone must be active.
2. **Verify ownership once, in GCP:**

   ```bash
   gcloud domains verify joscart.win
   ```

   It prints a TXT record (`google-site-verification=…`). Add it at Cloudflare as
   **DNS only** (grey cloud, not proxied). Verifying the apex covers every
   subdomain, so `lirify.` and `index.lirify.` need nothing extra.
3. **Enable the mappings** — repository/environment variable on `Lirify`:

   ```bash
   gh variable set ENABLE_DOMAIN_MAPPINGS --env Lirify --body true
   gh workflow run deploy.yml        # or push to main
   ```

   The deploy job now preflights `gcloud domains list-user-verified` and fails
   with the commands above if verification is missing, instead of a generic
   provider error minutes later.
4. **Read the exact records** from the run's job summary (*Lirify deploy* →
   `- web DNS: …`, `- index DNS: …`), or locally:

   ```bash
   cd infra
   terraform init -backend-config="bucket=lirify-514907-lirify-tfstate" -backend-config="prefix=lirify/state"
   terraform output web_domain_dns_records
   terraform output index_domain_dns_records
   ```

   Typical result: a `CNAME` per subdomain pointing at `ghs.googlehosted.com.`
   Add them as **CNAME** records (not A records) with the proxy **off**.
5. **Add them at Cloudflare as DNS only.** The orange-cloud proxy must be off for
   these records: a proxied CNAME terminates TLS at Cloudflare, so Google cannot
   validate the domain and the managed certificate never issues.
6. **Wait for the certificate**, then check:

   ```bash
   gcloud run domain-mappings describe --domain lirify.joscart.win --region us-central1
   ./scripts/check_domains.sh          # DNS, cert issuer (must be Google Trust), HTTP 200
   curl -sI https://lirify.joscart.win | head -3
   ```

   `CertificateProvisioned` and `Ready` must both be `True`. Issuance usually
   takes 15–60 minutes after DNS resolves.

The services keep using their `*.run.app` URLs for server-to-server traffic
(`PYTHON_BACKEND_URL`, `GRPC_TARGET`); only browsers use the custom domains.

> Production alternative: an external Application Load Balancer with a Serverless
> NEG gives one IP, Cloud Armor and certificates with DNS authorization. Domain
> mapping is used here because it is free and needs no load balancer.

## 10. Local indexing stack (standalone, laptop)

Everything that mutates the index runs here. The cloud stack stays read-only and
the two stacks never call each other: the indexer publishes straight into Atlas
and Qdrant.

### 10.1 GPU prerequisites

`core.py` embeds with sentence-transformers, so the container needs the NVIDIA
runtime:

```bash
sudo pacman -S --needed nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Gate: this must print the RTX 2050 before the compose stack can use it.
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

The model is `Qwen/Qwen3-Embedding-0.6B` (~1.2 GB) and is cached in the
`hf_cache` volume on first start. Deleting that volume forces a re-download.

The image installs **CPU torch** by default so it builds on hosts without the
NVIDIA container runtime. For GPU indexing, install the toolkit (privileged,
run it yourself), then use the GPU overlay:

```bash
sudo pacman -S --needed nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml \
  -f docker-compose.gpu.yml up -d --build local-indexer
```

The overlay builds CUDA 13.2 torch (`TORCH_INDEX_URL=.../cu132`), sets
`EMBEDDING_DEVICE=cuda`, `EMBEDDING_DTYPE=float16`, `EMBEDDING_BATCH_SIZE=8`
and adds the NVIDIA device reservation. `core.py` truncates each text to
`EMBEDDING_MAX_CHARS` (6000) to keep the 4 GB card within budget.

### 10.2 Start local-indexer + local-ui

```bash
docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml \
  up -d --build local-indexer local-ui
```

| Service | Port | Notes |
| --- | --- | --- |
| `local-indexer` | `50052` → container `50051` | gRPC only; ingestion + `core.py` + Atlas/Qdrant writes |
| `local-ui` | `8090` | `DASHBOARD_MODE=local`, the same dashboard plus controls |

`local-indexer` reads `MONGODB_URI` / `QDRANT_URL` / `QDRANT_API_KEY` from `.env`
and sets:

```
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIM=1024
QDRANT_COLLECTION=lirify_lyrics_qwen3
PUBLISH_ON_INDEX=1
LOAD_ON_START=1
```

`LOAD_ON_START=1` rehydrates committed songs from Atlas, so restarts keep the
library and duplicate detection. `PUBLISH_ON_INDEX=1` publishes after every
committed playlist.

The overlay also sets `QUERY_EMBED_URL=http://local-indexer:8080` on `api` and
`SEMANTIC_SEARCH=true` on `web`: web search posts the raw query to
`/db/embed`, which runs the same Qwen3-Embedding-0.6B model used for indexing,
then searches Qdrant. The first query after a cold start downloads the model
into the `hf_cache` volume.

For a deployment that cannot reach the laptop, add Cloudflare Workers AI
credentials to `.env` (`CF_ACCOUNT_ID`, `CF_API_TOKEN`, optional
`CF_EMBED_MODEL=@cf/qwen/qwen3-embedding-0.6b`). `python-backend` uses them when
`QUERY_EMBED_URL` is empty or unreachable. Check the model directly:

```bash
scripts/local/verify_cloudflare_embed.py "amor de verano" "winter love"
# prints dim (must be 1024), cosine matrix and the equivalent curl command
```

### 10.3 Index and publish

1. Open <http://localhost:8090>.
2. Paste a playlist URL → **Index now** (or queue several).
3. Progress appears in **Live events**; a commit writes songs to Atlas, LLM
   embeddings to Qdrant and bumps `index_stats.revision`.
4. **Publish to cloud** re-runs the same write for the whole in-memory index.
   It is mainly for a first backfill or after switching the Qdrant collection.
   An unchanged index is simply re-upserted; there is no local fingerprint file.
5. **Databases** (local-ui) is the CRUD/reset panel. It edits Atlas songs one at
   a time, deletes/re-embeds individual Qdrant points, rebuilds every vector, and
   offers **Reset to zero**: drop the collection, reload from Atlas and re-embed
   from scratch. The admin HTTP app listens on `127.0.0.1:8082` only.
6. The cloud replica notices the new revision within
   `INDEX_REFRESH_SECONDS`/`INDEX_CHECK_SECONDS`; to force it:

```bash
API=$(gcloud run services describe lirify-api --region us-central1 --format='value(status.url)')
curl -s -X POST "$API/admin/reload"
```

### 10.4 What is stored where

| State | Home |
| --- | --- |
| Tracks + `index_stats` | Atlas (`songs`, `index_stats`) |
| Qwen3-Embedding-0.6B vectors | Qdrant `lirify_lyrics_qwen3` |
| Terms, inverted index, TF-IDF | `local-indexer` process memory |

No matrices are stored in either database and no container writes to disk. There
are no `vocabulary.json` / `inverted_index.json` files to manage.

### 10.5 Run the indexer from source (dev container)

```bash
scripts/local/run_indexer_dev.sh
# gRPC:  127.0.0.1:50052
# admin: 127.0.0.1:8082  (/db/health, /db/overview)
```

The script mounts `services/local-indexer` over `/app` and the generated
`lirifypb` package, so edits to `core.py`, `pipeline.py`, `db_admin.py` or
`admin_api.py` apply after `docker restart lirify-local-indexer-dev`. It runs
with `LOAD_ON_START=0` for a fast boot; the database panel reloads from Atlas on
demand. The HF model cache is the shared `lirify_hf_cache` volume.

### 10.6 Inspect the local engine

```bash
grpcurl -proto proto/lirify.proto -plaintext localhost:50052 \
  lirify.v1.LirifyIndexerService/GetLocalIndex

docker compose -f docker-compose.yml -f docker-compose.local-indexer.yml \
  logs -f local-indexer
```

## 11. Day-2 operations

| Task | How |
| --- | --- |
| Deploy a serving change | Push to `main`. |
| Re-deploy the same commit | Actions → Deploy → Run workflow. |
| Rotate the bot key | Update the `BOT_INGEST_API_KEY` secret, re-run the workflow (Terraform writes a new secret version and rolls the revision). |
| Rotate the Atlas password | Update `MONGODB_URI`, re-run. |
| Index a playlist | Local stack → `http://localhost:8090` → **Index now**. |
| Publish/backfill the cloud | Local dashboard → **Publish to cloud**, then `POST /admin/reload`. |
| Inspect job history | Local dashboard → Queue, or the cloud dashboard (read-only). |
| Change capacity | `MAX_INDEXED_SONGS` defaults to 3000 with `python_memory = 1Gi` (~400 MB at 1700 songs). Raise both together; `-1` = unlimited on the laptop. |
| Change embedding model/collection | New `QDRANT_COLLECTION` + `QDRANT_VECTOR_SIZE` everywhere, then publish. Never reuse a collection with a different dimension. |
| Roll back | Re-run the workflow for the previous commit, or `gcloud run services update-traffic lirify-api --to-revisions=<rev>=100`. |

### Cost safety

```bash
# Alert if anything unexpected starts costing money
gcloud billing budgets create --billing-account=XXXXXX-XXXXXX-XXXXXX \
  --display-name="Lirify guard" --budget-amount=1USD \
  --threshold-rule=percent=0.5 --threshold-rule=percent=1.0
```

Free-tier ceilings that this stack respects: 2M Cloud Run requests/month,
360k GiB-s, 180k vCPU-s, 0.5 GB Artifact Registry, 6 active Secret Manager
versions. Cloud Run `max_instances = 1` prevents runaway scaling.

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `deploy` fails: `PERMISSION_DENIED: iam.serviceAccounts.create` | Bootstrap roles stale | Re-apply `infra/bootstrap` (it now grants `roles/iam.serviceAccountAdmin`). |
| Web UI shows API offline, `/healthz` 200 | `GRPC_TARGET` wrong or python cold | Check `gcloud run services describe lirify-web --format=yaml | grep GRPC_TARGET`; first request after idle takes ~5 s. |
| gRPC calls fail with `PermissionDenied` | `python_public = false` | Set it back to `true`, or give the web UIs ID-token auth. |
| `stats` shows `storage.tracks = memory` | `MONGODB_URI` not injected | Check the Secret Manager version exists and the revision has the env var. |
| Recommendations always empty | Qdrant unreachable, empty, or wrong collection | `storage.vectors` must be `qdrant`; confirm `QDRANT_COLLECTION=lirify_lyrics_qwen3` and run **Publish to cloud** from `local-ui`. |
| `403` on `/index` | Cloud api is read-only | Expected: index from the laptop stack. |
| `UNIMPLEMENTED` on `IndexPlaylist` | Serving replica has indexing disabled | Expected: call `local-indexer:50051` instead. |
| `503` / empty vectors after switching models | 1024-dim collection not published yet | Run **Publish to cloud**; use a new `QDRANT_COLLECTION`, never the 256-dim one. |
| Index job fails with `bot_check` | YouTube anti-bot challenge on the laptop egress | Retry later, or pass cookies to yt-dlp via a custom image. |
| Index job fails: `Index capacity guard` | `Index capacity guard` | The service serves the newest `MAX_INDEXED_SONGS` (default 3000); raise the limit **and** memory, or prune. Measured: 1000 songs ≈ 227 MB RSS, 1661 ≈ 401 MB. |
| Certificate stays `Provisioning` | DNS missing/typo'd (check the double-i host) | Fix DNS; re-check `gcloud run domain-mappings describe`. |
| Atlas `bad auth : Authentication failed` | `authSource` points at the app database, but Atlas users live in `admin` | Append `?authSource=admin` to `MONGODB_URI` (and `MONGO_ROOT_URI`). |
| Atlas connection timeouts | Network Access missing `0.0.0.0/0` | Add it in Atlas → Network Access. |
| `db-init` logs `cannot create user ... continuing` | Atlas manages users in its console | Expected; create/rotate the DB user in Atlas, keep `MONGODB_URI` in sync. |
