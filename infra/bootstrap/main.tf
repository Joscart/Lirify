# One-time bootstrap for the Lirify GCP project.
#
# Creates the pieces that must exist BEFORE the first CI run:
#   * GCS bucket for the Terraform remote state of infra/
#   * Artifact Registry repository the CI workflow pushes images into
#   * Workload Identity Federation pool/provider and the deploy service account
#
# Run once, as a project owner:
#   cd infra/bootstrap
#   terraform init
#   terraform apply -var project_id=YOUR_PROJECT
#
# State for this stack is local on purpose: it creates the bucket that stores the
# state of the main stack. Keep the generated terraform.tfstate somewhere safe.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.8"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Tier 1 region shared with the main stack."
  type        = string
  default     = "us-central1"
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy."
  type        = string
  default     = "joscart/lirify"
}

variable "state_bucket_name" {
  description = "Override the state bucket name (must be globally unique). Empty = <project>-lirify-tfstate."
  type        = string
  default     = ""
}

locals {
  services     = ["run", "artifactregistry", "secretmanager", "iam", "cloudresourcemanager", "serviceusage", "storage", "sts"]
  state_bucket = var.state_bucket_name != "" ? var.state_bucket_name : "${var.project_id}-lirify-tfstate"
  deploy_sa_id = "lirify-deployer"
  pool_id      = "github-pool"
  provider_id  = "github-provider"
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project            = var.project_id
  service            = "${each.value}.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "tfstate" {
  project                     = var.project_id
  name                        = local.state_bucket
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 10
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}

resource "google_artifact_registry_repository" "lirify" {
  project       = var.project_id
  location      = var.region
  repository_id = "lirify"
  description   = "Lirify container images (python-backend, astro-webui, go-webui)"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 2
    }
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state = "UNTAGGED"
    }
  }

  depends_on = [google_project_service.enabled]
}

# --- Workload Identity Federation ------------------------------------------

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = local.pool_id
  display_name              = "GitHub Actions"
  description               = "OIDC pool for GitHub Actions deployments of Lirify"

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = local.provider_id
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Only this repository (and its main branch, via the workflow) may mint tokens.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = local.deploy_sa_id
  display_name = "Lirify Terraform deployer (GitHub Actions)"
}

resource "google_service_account_iam_member" "deployer_wi" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

locals {
  deploy_roles = [
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    # Cloud Run identities (python-backend, astro-webui, go-webui) are created by infra/.
    "roles/iam.serviceAccountAdmin",
    "roles/artifactregistry.writer",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
    "roles/resourcemanager.projectIamAdmin",
  ]
}

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deploy_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

output "state_bucket" {
  description = "Value for the TF_STATE_BUCKET repository variable."
  value       = google_storage_bucket.tfstate.name
}

output "artifact_registry" {
  description = "Docker repository prefix used by CI."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.lirify.repository_id}"
}

output "workload_identity_provider" {
  description = "Value for the GCP_WORKLOAD_IDENTITY_PROVIDER repository variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deploy_service_account" {
  description = "Value for the GCP_DEPLOY_SERVICE_ACCOUNT repository variable."
  value       = google_service_account.deployer.email
}
