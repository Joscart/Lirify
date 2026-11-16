# Lirify deployment runbook

Everything in this file is the **manual** part of the pipeline. Code, Terraform and
CI are in the repository; the steps below create the accounts and identities that
CI cannot create for itself.

Work top to bottom. Steps 1–6 are one-time. Steps 7–10 are the first deploy.

> **Domains.** `lirify.joscart.win` (player) and `index.lirify.joscart.win`
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
5. Nothing else to configure: the backend creates the `lirify_lyrics` collection
   (256-dim, cosine) on first index, and backfills vectors for existing tracks if
   the collection is ever empty.

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
| `WEB_DOMAIN` | `lirify.joscart.win` |
| `INDEX_DOMAIN` | `index.lirify.joscart.win` |
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

curl -s "$API/health"                       # {"status":"ok","storage":{"tracks":"mongodb","vectors":"qdrant"}}
curl -s "$API/stats" | head -c 400
curl -s "$API/api/v1/bot/health" -H "Authorization: Bearer $BOT_INGEST_API_KEY"

# gRPC over TLS :443 (the same path the web UIs use)
grpcurl -proto proto/lirify.proto \
  -H "x-lirify-client: runbook" \
  "$(echo "$API" | sed 's|https://||'):443" lirify.v1.LirifyService/GetIndexStats
```

If `grpcurl` returns `Unknown` for an error response, confirm the service is the
one built from this repository: `python-backend` sends initial metadata before
aborting so gRPC status codes survive the in-container h2c mux.

---

## 9. Custom domains and managed certificates

Cloud Run domain mappings only work for domains **verified in Google Search
Console** by an owner of the GCP project.

1. Verify ownership of `joscart.win`:

   ```bash
   gcloud domains verify joscart.win
   ```

   Follow the browser flow (Search Console → add the domain → TXT record).
2. Deploy with mappings enabled (either set the `ENABLE_DOMAIN_MAPPINGS` variable to
   `true` and re-run the workflow, or dispatch the workflow with
   `enable_domain_mappings: true`).
3. Read the exact records Terraform created:

   ```bash
   cd infra
   terraform init -backend-config="bucket=YOUR_STATE_BUCKET" -backend-config="prefix=lirify/state"
   terraform output web_domain_dns_records
   terraform output index_domain_dns_records
   ```

   Each entry is `{type, name, value}`. Typical output:

   | Host | Type | Name | Value |
   | --- | --- | --- | --- |
   | `lirify.joscart.win` | `CNAME` | `lirify` | `ghs.googlehosted.com.` |
   | `index.lirify.joscart.win` | `CNAME` | `index` | `ghs.googlehosted.com.` |
   | apex (`joscart.win`) | `A` / `AAAA` | `@` | `216.239.32.21` … |

   Add them at your DNS provider exactly as printed. CNAMEs must not be
   proxied/ flattened by a CDN in a way that hides the target.
4. Wait for the certificate:

   ```bash
   gcloud run domain-mappings describe --domain lirify.joscart.win --region us-central1
   ```

   The `CertificateProvisioned` and `Ready` conditions become `True` once DNS has
   propagated and Google issues the certificate (usually 15–60 minutes).
5. Confirm HTTPS:

   ```bash
   curl -sI https://lirify.joscart.win | head -3
   curl -sI https://index.lirify.joscart.win | head -3
   ```

> Production alternative: Google recommends an external Application Load Balancer
> with a Serverless NEG instead of domain mappings. It gives you one IP, Cloud
> Armor and managed certificates with DNS authorization. Domain mapping is used
> here because it is free and needs no load balancer.

---

## 10. Day-2 operations

| Task | How |
| --- | --- |
| Deploy a change | Push to `main`. |
| Re-deploy the same commit | Actions → Deploy → Run workflow. |
| Rotate the bot key | Update the `BOT_INGEST_API_KEY` secret, re-run the workflow (Terraform writes a new secret version and rolls the revision). |
| Rotate the Atlas password | Update `MONGODB_URI`, re-run. |
| Index a playlist as an operator | `https://index.lirify.joscart.win` → **Index now**. |
| Index a playlist as an agent | `skills/lirify-playlist-indexer` (see `SKILL.md`). |
| Inspect job history | Go dashboard → Queue, or `curl $API/queue`. |
| Change capacity | `MAX_INDEXED_SONGS` defaults to 3000 with `python_memory = 1Gi` (~400 MB at 1700 songs). Raise both together; `-1` = unlimited for local only. |
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

## 11. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `deploy` fails: `PERMISSION_DENIED: iam.serviceAccounts.create` | Bootstrap roles stale | Re-apply `infra/bootstrap` (it now grants `roles/iam.serviceAccountAdmin`). |
| Web UI shows API offline, `/healthz` 200 | `GRPC_TARGET` wrong or python cold | Check `gcloud run services describe lirify-web --format=yaml | grep GRPC_TARGET`; first request after idle takes ~5 s. |
| gRPC calls fail with `PermissionDenied` | `python_public = false` | Set it back to `true`, or give the web UIs ID-token auth. |
| `stats` shows `storage.tracks = memory` | `MONGODB_URI` not injected | Check the Secret Manager version exists and the revision has the env var. |
| Recommendations always empty | Qdrant unreachable or empty | `storage.vectors` must be `qdrant`; the service backfills vectors on boot. |
| Index job fails with `bot_check` | YouTube anti-bot challenge on the Cloud Run egress | Retry later, or pass cookies to yt-dlp via a custom image. |
| Index job fails: `Index capacity guard` | `Index capacity guard` | The service serves the newest `MAX_INDEXED_SONGS` (default 3000); raise the limit **and** memory, or prune. Measured: 1000 songs ≈ 227 MB RSS, 1661 ≈ 401 MB. |
| Certificate stays `Provisioning` | DNS missing/typo'd (check the double-i host) | Fix DNS; re-check `gcloud run domain-mappings describe`. |
| Atlas `bad auth : Authentication failed` | `authSource` points at the app database, but Atlas users live in `admin` | Append `?authSource=admin` to `MONGODB_URI` (and `MONGO_ROOT_URI`). |
| Atlas connection timeouts | Network Access missing `0.0.0.0/0` | Add it in Atlas → Network Access. |
| `db-init` logs `cannot create user ... continuing` | Atlas manages users in its console | Expected; create/rotate the DB user in Atlas, keep `MONGODB_URI` in sync. |
