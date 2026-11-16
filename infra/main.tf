locals {
  services = ["run", "artifactregistry", "secretmanager", "iam", "cloudresourcemanager", "compute"]

  labels = merge(
    {
      app         = "lirify"
      environment = var.environment
      managed-by  = "terraform"
    },
    var.labels,
  )

  python_service = "lirify-api"
  web_service    = "lirify-web"
  go_service     = "lirify-index"

  # Created once by infra/bootstrap so CI can push images before this stack runs.
  artifact_registry = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repository}"

  secret_ids = {
    mongodb_uri        = "lirify-mongodb-uri"
    qdrant_url         = "lirify-qdrant-url"
    qdrant_api_key     = "lirify-qdrant-api-key"
    bot_ingest_api_key = "lirify-bot-ingest-api-key"
  }
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project            = var.project_id
  service            = "${each.value}.googleapis.com"
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Service accounts (one per service, least privilege)
# ---------------------------------------------------------------------------

resource "google_service_account" "python" {
  project      = var.project_id
  account_id   = "lirify-python-backend"
  display_name = "Lirify python-backend (Cloud Run)"
}

resource "google_service_account" "web" {
  project      = var.project_id
  account_id   = "lirify-astro-webui"
  display_name = "Lirify astro-webui (Cloud Run)"
}

resource "google_service_account" "go" {
  project      = var.project_id
  account_id   = "lirify-go-webui"
  display_name = "Lirify go-webui (Cloud Run)"
}

# ---------------------------------------------------------------------------
# Secret Manager: python-backend is the only consumer
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "secrets" {
  for_each = local.secret_ids

  project   = var.project_id
  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "secrets" {
  for_each = local.secret_ids

  secret = google_secret_manager_secret.secrets[each.key].id

  secret_data = {
    mongodb_uri        = var.mongodb_uri
    qdrant_url         = var.qdrant_url
    qdrant_api_key     = var.qdrant_api_key
    bot_ingest_api_key = var.bot_ingest_api_key
  }[each.key]
}

resource "google_secret_manager_secret_iam_member" "python_access" {
  for_each = local.secret_ids

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.python.email}"
}

# ---------------------------------------------------------------------------
# python-backend: REST + gRPC (h2c) on one port, stateless
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "python" {
  project             = var.project_id
  name                = local.python_service
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.python.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.python_max_instances
    }

    max_instance_request_concurrency = 20
    timeout                          = "600s"

    containers {
      image = var.python_image

      # `h2c` is what makes Cloud Run keep HTTP/2 end-to-end: gRPC from the two
      # web UIs and HTTP/1.1 JSON for the bot API both land on this port, and the
      # in-container mux (Caddyfile) routes by content-type.
      ports {
        name           = "h2c"
        container_port = 8080
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = var.python_cpu
          memory = var.python_memory
        }
      }

      # PORT is injected by Cloud Run (reserved name); the image defaults to 8080
      # and run.sh honours the injected value.
      env {
        name  = "GRPC_PORT"
        value = "50051"
      }
      env {
        name  = "HTTP_PORT"
        value = "8000"
      }
      env {
        name  = "MONGODB_DB"
        value = var.mongodb_db
      }
      env {
        name  = "QDRANT_COLLECTION"
        value = var.qdrant_collection
      }
      env {
        name  = "QDRANT_VECTOR_SIZE"
        value = tostring(var.qdrant_vector_size)
      }
      env {
        name  = "MAX_INDEXED_SONGS"
        value = tostring(var.max_indexed_songs)
      }
      env {
        name  = "MAX_JOB_ATTEMPTS"
        value = tostring(var.max_job_attempts)
      }
      env {
        name  = "RETRY_INTERVAL_SECONDS"
        value = tostring(var.retry_interval_seconds)
      }
      env {
        name  = "BOT_RATE_LIMIT"
        value = tostring(var.bot_rate_limit)
      }
      env {
        name  = "BOT_RATE_WINDOW_SECONDS"
        value = tostring(var.bot_rate_window_seconds)
      }
      env {
        name  = "BOT_CHECK_RETRY_MIN_SECONDS"
        value = tostring(var.bot_check_retry_min_seconds)
      }
      env {
        name  = "BOT_CHECK_RETRY_MAX_SECONDS"
        value = tostring(var.bot_check_retry_max_seconds)
      }
      env {
        name  = "PUBLIC_RATE_LIMIT_PER_MINUTE"
        value = tostring(var.public_rate_limit_per_minute)
      }

      env {
        name = "MONGODB_URI"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["mongodb_uri"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "QDRANT_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["qdrant_url"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "QDRANT_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["qdrant_api_key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "BOT_INGEST_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["bot_ingest_api_key"].secret_id
            version = "latest"
          }
        }
      }

      # Caddy binds the port before uvicorn is ready, so a TCP probe would let
      # traffic in while /health still returns 502. Probe the real endpoint: a
      # cold start has to open Atlas + Qdrant and rebuild the index first.
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 5
        failure_threshold     = 36
      }

      # Cloud Run does not support TCP sockets in *liveness* probes (only in
      # startup probes). The container's Caddy mux answers HTTP GET on /health
      # from uvicorn, so probe that instead of the gRPC channel.
      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds    = 60
        timeout_seconds   = 5
        failure_threshold = 3
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_secret_manager_secret_iam_member.python_access,
  ]
}

# ---------------------------------------------------------------------------
# astro-webui: SSR player
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "web" {
  project             = var.project_id
  name                = local.web_service
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.web.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.web_max_instances
    }

    max_instance_request_concurrency = 80
    timeout                          = "300s"

    containers {
      image = var.web_image

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = var.web_memory
        }
      }

      env {
        name  = "HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "PROTO_PATH"
        value = "/app/proto/lirify.proto"
      }
      env {
        name  = "PYTHON_BACKEND_URL"
        value = google_cloud_run_v2_service.python.uri
      }
      env {
        name  = "GRPC_TARGET"
        value = "${trimprefix(google_cloud_run_v2_service.python.uri, "https://")}:443"
      }
      env {
        name  = "GRPC_INSECURE"
        value = "false"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 3
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 30
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds    = 60
        timeout_seconds   = 5
        failure_threshold = 3
      }
    }
  }
}

# ---------------------------------------------------------------------------
# go-webui: playlist indexer dashboard
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "go" {
  project             = var.project_id
  name                = local.go_service
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = google_service_account.go.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.go_max_instances
    }

    max_instance_request_concurrency = 80
    timeout                          = "300s"

    containers {
      image = var.go_image

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = var.go_memory
        }
      }

      env {
        name  = "GRPC_TARGET"
        value = "${trimprefix(google_cloud_run_v2_service.python.uri, "https://")}:443"
      }
      env {
        name  = "GRPC_TLS"
        value = "true"
      }
      env {
        name  = "PYTHON_BACKEND_URL"
        value = google_cloud_run_v2_service.python.uri
      }
      env {
        name  = "PUBLIC_PLAYER_URL"
        value = "https://${var.web_domain}"
      }
      env {
        name  = "WATCH_INTERVAL_SECONDS"
        value = "5"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 2
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 20
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds    = 60
        timeout_seconds   = 5
        failure_threshold = 3
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Invoker bindings
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service_iam_member" "python_public" {
  count = var.python_public ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.python.location
  name     = google_cloud_run_v2_service.python.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "go_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.go.location
  name     = google_cloud_run_v2_service.go.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Custom domains (managed certificates)
# ---------------------------------------------------------------------------

resource "google_cloud_run_domain_mapping" "web" {
  count = var.enable_domain_mappings ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.web_domain

  metadata {
    namespace = var.project_id
    labels    = local.labels
  }

  spec {
    route_name       = google_cloud_run_v2_service.web.name
    certificate_mode = "AUTOMATIC"
  }

  lifecycle {
    ignore_changes = [metadata[0].annotations]
  }
}

resource "google_cloud_run_domain_mapping" "go" {
  count = var.enable_domain_mappings ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.index_domain

  metadata {
    namespace = var.project_id
    labels    = local.labels
  }

  spec {
    route_name       = google_cloud_run_v2_service.go.name
    certificate_mode = "AUTOMATIC"
  }

  lifecycle {
    ignore_changes = [metadata[0].annotations]
  }
}
