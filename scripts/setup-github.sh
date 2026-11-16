#!/usr/bin/env bash
# Push the Lirify deployment configuration into a GitHub repository.
#
# Variables (non-secret) are always written. Secrets are written only when the
# matching environment variable is set, so this script is safe to re-run.
#
#   export GCP_PROJECT_ID=lirify-514907
#   export GCP_REGION=us-central1
#   export GCP_WORKLOAD_IDENTITY_PROVIDER=projects/.../providers/github-provider
#   export GCP_DEPLOY_SERVICE_ACCOUNT=lirify-deployer@lirify-514907.iam.gserviceaccount.com
#   export TF_STATE_BUCKET=lirify-514907-lirify-tfstate
#   export WEB_DOMAIN=lirify.joscart.win
#   export INDEX_DOMAIN=index.lirify.joscart.win
#   export ENABLE_DOMAIN_MAPPINGS=false
#   export MONGODB_URI=... QDRANT_URL=... QDRANT_API_KEY=... BOT_INGEST_API_KEY=...
#   ./scripts/setup-github.sh [--repo owner/name]
set -euo pipefail

REPO_ARGS=()
if [[ "${1:-}" == "--repo" && -n "${2:-}" ]]; then
  REPO_ARGS=(--repo "$2")
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh (GitHub CLI) is required: https://cli.github.com" >&2
  exit 1
fi

VARIABLES=(
  GCP_PROJECT_ID
  GCP_REGION
  GCP_WORKLOAD_IDENTITY_PROVIDER
  GCP_DEPLOY_SERVICE_ACCOUNT
  TF_STATE_BUCKET
  WEB_DOMAIN
  INDEX_DOMAIN
  ENABLE_DOMAIN_MAPPINGS
)

SECRETS=(
  MONGODB_URI
  QDRANT_URL
  QDRANT_API_KEY
  BOT_INGEST_API_KEY
)

missing=()
for name in "${VARIABLES[@]}"; do
  [[ -n "${!name:-}" ]] || missing+=("$name")
done
if ((${#missing[@]})); then
  echo "Missing required environment variables:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  echo "See infra/BOOTSTRAP.md for the values recorded from terraform output." >&2
  exit 1
fi

for name in "${VARIABLES[@]}"; do
  gh variable set "$name" --body "${!name}" "${REPO_ARGS[@]}"
  echo "variable  $name"
done

for name in "${SECRETS[@]}"; do
  if [[ -n "${!name:-}" ]]; then
    gh secret set "$name" --body "${!name}" "${REPO_ARGS[@]}"
    echo "secret    $name"
  else
    echo "skipped   $name (not set in the environment)"
  fi
done

echo
echo "Current repository configuration:"
gh variable list "${REPO_ARGS[@]}" || true
gh secret list "${REPO_ARGS[@]}" || true
