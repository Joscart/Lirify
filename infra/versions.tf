terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.8"
    }
  }

  # Remote state lives in GCS so CI runners and humans share one lock.
  # The bucket is injected by CI (`-backend-config=...`) and documented in
  # docs/DEPLOYMENT.md. Local runs can use:
  #   terraform init -backend=false
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
