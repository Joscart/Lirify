# Bootstrap outputs — `lirify-514907`

Recorded from `terraform apply` in `infra/bootstrap/`. These four values are the
GitHub **repository variables** the deploy workflow needs.

| Terraform output | Value | GitHub variable |
| --- | --- | --- |
| `artifact_registry` | `us-central1-docker.pkg.dev/lirify-514907/lirify` | (implicit: derived from `GCP_PROJECT_ID` + `GCP_REGION`, used by the workflow) |
| `deploy_service_account` | `lirify-deployer@lirify-514907.iam.gserviceaccount.com` | `GCP_DEPLOY_SERVICE_ACCOUNT` |
| `state_bucket` | `lirify-514907-lirify-tfstate` | `TF_STATE_BUCKET` |
| `workload_identity_provider` | `projects/474677577871/locations/global/workloadIdentityPools/github-pool/providers/github-provider` | `GCP_WORKLOAD_IDENTITY_PROVIDER` |

Project: `lirify-514907` · Project number: `474677577871` · Region: `us-central1`
State prefix: `lirify/state` · Domain: `lirify.joscart.win` / `index.joscart.win`

## Set everything at once

```bash
export GCP_PROJECT_ID=lirify-514907
export GCP_REGION=us-central1
export GCP_WORKLOAD_IDENTITY_PROVIDER=projects/474677577871/locations/global/workloadIdentityPools/github-pool/providers/github-provider
export GCP_DEPLOY_SERVICE_ACCOUNT=lirify-deployer@lirify-514907.iam.gserviceaccount.com
export TF_STATE_BUCKET=lirify-514907-lirify-tfstate
export WEB_DOMAIN=lirify.joscart.win
export INDEX_DOMAIN=index.joscart.win
export ENABLE_DOMAIN_MAPPINGS=false

./scripts/setup-github.sh            # variables + secret presence check
```

Secrets (`MONGODB_URI`, `QDRANT_URL`, `QDRANT_API_KEY`, `BOT_INGEST_API_KEY`) are
never stored in this file. Add them with `gh secret set` or let
`scripts/setup-github.sh` read them from your environment.

## Why the first pipeline run can fail

`terraform apply` needs real values for those four secrets, and Cloud Run needs
the Artifact Registry repository to exist **before** images are pushed. The repo
now exists (this bootstrap ran), so the remaining failure modes are:

| Failure | Meaning | Fix |
| --- | --- | --- |
| `images` job: `denied: Permission "artifactregistry.repositories.uploadArtifacts"` | WIF/auth or missing role | Re-apply `infra/bootstrap` (it grants `roles/artifactregistry.writer`). |
| `deploy` job: `Error: No value for required variable "mongodb_uri"` | Secret not set in GitHub | `gh secret set MONGODB_URI` |
| `deploy` job: `Error acquiring the state lock` / `bucket ... does not exist` | `TF_STATE_BUCKET` wrong or bucket in another project | Check the repository variable against this file. |
| `deploy` job: `PERMISSION_DENIED` enabling an API | API just enabled | Re-run the job (Terraform is idempotent). |
| `smoke` job: 503 on `/healthz` | Cold start / secrets not injected yet | Re-run; check `gcloud run services describe lirify-api`. |
