variable "project_id" {
  description = "GCP project id that hosts the Lirify services."
  type        = string
}

variable "region" {
  description = "Cloud Run region. us-central1 and us-east1 are Tier 1 (Always Free) regions."
  type        = string
  default     = "us-central1"

  validation {
    condition     = contains(["us-central1", "us-east1", "us-west1"], var.region)
    error_message = "Use a Tier 1 free-tier region: us-central1, us-east1 or us-west1."
  }
}

variable "artifact_repository" {
  description = "Artifact Registry repository id created by infra/bootstrap."
  type        = string
  default     = "lirify"
}

variable "environment" {
  description = "Environment label applied to every resource."
  type        = string
  default     = "prod"
}

# --- images (built and pushed by GitHub Actions, pinned by digest) ----------

variable "python_image" {
  description = "Artifact Registry image for python-backend, ideally pinned by @sha256 digest."
  type        = string
}

variable "web_image" {
  description = "Artifact Registry image for astro-webui, ideally pinned by @sha256 digest."
  type        = string
}

variable "go_image" {
  description = "Artifact Registry image for go-webui, ideally pinned by @sha256 digest."
  type        = string
}

# --- domains ---------------------------------------------------------------

variable "web_domain" {
  description = "Public host for the Astro player."
  type        = string
  default     = "lirify.joscart.win"
}

variable "index_domain" {
  description = "Public host for the Go playlist indexer dashboard."
  type        = string
  default     = "index.lirify.joscart.win"
}

variable "enable_domain_mappings" {
  description = "Create Cloud Run domain mappings. Requires the domains to be verified in Search Console first."
  type        = bool
  default     = true
}

# --- free-tier tuning ------------------------------------------------------

variable "python_memory" {
  description = <<-EOT
    Memory for python-backend. The in-process TF-IDF index needs ~400 MB for
    ~1700 songs and ~800 MB for ~4000; 1Gi keeps the whole catalogue servable
    while remaining inside the Cloud Run free GiB-second allowance for
    scale-to-zero usage.
  EOT
  type        = string
  default     = "1Gi"
}

variable "python_cpu" {
  description = "vCPU for python-backend. Keep at 1 to stay inside the Always Free tier."
  type        = string
  default     = "1"
}

variable "python_max_instances" {
  description = "Hard ceiling for python-backend instances. 1 keeps cost at zero."
  type        = number
  default     = 1
}

variable "web_memory" {
  type    = string
  default = "512Mi"
}

variable "go_memory" {
  type    = string
  default = "256Mi"
}

variable "web_max_instances" {
  type    = number
  default = 1
}

variable "go_max_instances" {
  type    = number
  default = 1
}

variable "python_public" {
  description = <<-EOT
    Allow unauthenticated invocations of python-backend.
    Required for the browser-facing bot API and for gRPC from the two web UIs,
    which do not mint Google ID tokens. Writes stay protected by BOT_INGEST_API_KEY;
    reads only expose the public lyric index. Set to false if you front the
    service with an authenticated load balancer or add ID-token auth.
  EOT
  type        = bool
  default     = true
}

# --- application configuration ---------------------------------------------

variable "mongodb_uri" {
  description = "MongoDB Atlas connection string (mongodb+srv://...). Stored in Secret Manager."
  type        = string
  sensitive   = true
}

variable "mongodb_db" {
  description = "Atlas database name."
  type        = string
  default     = "lirify"
}

variable "qdrant_url" {
  description = "Qdrant Cloud cluster URL, e.g. https://xxxx.eu-central.aws.cloud.qdrant.io:6333"
  type        = string
  sensitive   = true
}

variable "qdrant_api_key" {
  description = "Qdrant Cloud API key."
  type        = string
  sensitive   = true
}

variable "bot_ingest_api_key" {
  description = "Bearer token external AI agents use for POST /api/v1/bot/index-playlist."
  type        = string
  sensitive   = true
}

variable "bot_rate_limit" {
  description = "Bot submissions allowed per window, per API key. 0 or -1 disables the limit (local compose)."
  type        = number
  default     = 30
}

variable "public_rate_limit_per_minute" {
  description = "Requests per minute per client IP across the public REST surface. 0 or -1 disables it (local compose)."
  type        = number
  default     = 120
}

variable "bot_rate_window_seconds" {
  type    = number
  default = 3600
}

variable "bot_check_retry_min_seconds" {
  description = "Lower bound of the randomised retry window suggested to agents after a YouTube bot check."
  type        = number
  default     = 900
}

variable "bot_check_retry_max_seconds" {
  description = "Upper bound of the randomised retry window suggested to agents after a YouTube bot check."
  type        = number
  default     = 7200
}

variable "index_refresh_seconds" {
  description = "How often a running instance compares the shared index revision and reloads. 0 disables."
  type        = number
  default     = 60
}

variable "max_indexed_songs" {
  description = <<-EOT
    Capacity guard for the in-process TF-IDF index. Default 3000 covers a
    ~1700-song catalogue with headroom at 1Gi. Set -1 for unlimited — only on a
    memory-rich local stack. Raising this without raising python_memory will
    OOM-kill the revision.
  EOT
  type        = number
  default     = 3000
}

variable "max_job_attempts" {
  type    = number
  default = 8
}

variable "retry_interval_seconds" {
  type    = number
  default = 300
}

variable "qdrant_vector_size" {
  type    = number
  default = 256
}

variable "qdrant_collection" {
  type    = string
  default = "lirify_lyrics"
}

variable "labels" {
  description = "Extra labels merged onto every resource."
  type        = map(string)
  default     = {}
}
