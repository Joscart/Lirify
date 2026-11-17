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
#   export INDEX_DOMAIN=index.joscart.win
#   export ENABLE_DOMAIN_MAPPINGS=false
#   export MONGODB_URI=... QDRANT_URL=... QDRANT_API_KEY=... BOT_INGEST_API_KEY=...
#   ./scripts/setup-github.sh [--repo owner/name] [--env Lirify] [--check]
#
# --env NAME      store variables/secrets on that GitHub environment instead of
#                 the repository. The workflow declares `environment:` on every
#                 job that reads configuration, so both levels work — but pick
#                 one deliberately: environment-scoped values are invisible to
#                 jobs that do not declare the environment.
# --check         only report what is configured at each level; change nothing.
set -euo pipefail

REPO_ARGS=()
ENV_NAME=""
CHECK_ONLY=0
while (($#)); do
  case "$1" in
    --repo) REPO_ARGS=(--repo "$2"); shift 2 ;;
    --env) ENV_NAME="$2"; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ENV_ARGS=()
if [[ -n "$ENV_NAME" ]]; then
  ENV_ARGS=(--env "$ENV_NAME")
fi

if ((CHECK_ONLY)); then
  echo "repository variables:"
  gh variable list "${REPO_ARGS[@]}" 2>/dev/null || true
  echo "repository secrets:"
  gh secret list "${REPO_ARGS[@]}" 2>/dev/null || true
  if [[ -n "$ENV_NAME" ]]; then
    echo "environment '$ENV_NAME' variables:"
    gh variable list --env "$ENV_NAME" "${REPO_ARGS[@]}" 2>/dev/null || true
    echo "environment '$ENV_NAME' secrets:"
    gh secret list --env "$ENV_NAME" "${REPO_ARGS[@]}" 2>/dev/null || true
  fi
  echo
  echo "The workflow reads '$ENV_NAME' (DEPLOY_ENVIRONMENT or 'Lirify')."
  echo "Values at the other level are invisible to it."
  exit 0
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
  gh variable set "$name" --body "${!name}" "${ENV_ARGS[@]}" "${REPO_ARGS[@]}"
  echo "variable  $name${ENV_NAME:+ (env $ENV_NAME)}"
done

for name in "${SECRETS[@]}"; do
  if [[ -n "${!name:-}" ]]; then
    gh secret set "$name" --body "${!name}" "${ENV_ARGS[@]}" "${REPO_ARGS[@]}"
    echo "secret    $name${ENV_NAME:+ (env $ENV_NAME)}"
  else
    echo "skipped   $name (not set in the environment)"
  fi
done

echo
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -n "$ENV_NAME" ]]; then
  "$SELF_DIR/setup-github.sh" --check --env "$ENV_NAME" "${REPO_ARGS[@]}" || true
else
  "$SELF_DIR/setup-github.sh" --check "${REPO_ARGS[@]}" || true
fi
