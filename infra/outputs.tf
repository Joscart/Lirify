# ---------------------------------------------------------------------------
# Service endpoints
# ---------------------------------------------------------------------------

output "python_backend_url" {
  description = "Cloud Run URL for python-backend (REST + gRPC h2c on :443)."
  value       = google_cloud_run_v2_service.python.uri
}

output "python_grpc_target" {
  description = "Value for GRPC_TARGET in astro-webui / go-webui."
  value       = "${trimprefix(google_cloud_run_v2_service.python.uri, "https://")}:443"
}

output "astro_webui_url" {
  description = "Cloud Run URL for the Astro player."
  value       = google_cloud_run_v2_service.web.uri
}

output "go_webui_url" {
  description = "Cloud Run URL for the Go indexer dashboard."
  value       = google_cloud_run_v2_service.go.uri
}

output "artifact_registry" {
  description = "Docker repository prefix used by CI (owned by infra/bootstrap)."
  value       = local.artifact_registry
}

# ---------------------------------------------------------------------------
# Custom domain DNS records
#
# Cloud Run provisions a managed certificate once these records resolve. The
# values are only known after the mapping controller reconciles (usually under a
# minute, but `terraform apply` may finish first; re-run `terraform refresh` or
# read the outputs on the next apply).
# ---------------------------------------------------------------------------

output "web_domain_dns_records" {
  description = "DNS records to create for the Astro player domain."
  value = var.enable_domain_mappings ? [
    for record in try(google_cloud_run_domain_mapping.web[0].status[0].resource_records, []) : {
      type  = record.type
      name  = record.name
      value = record.rrdata
    }
  ] : []
}

output "index_domain_dns_records" {
  description = "DNS records to create for the Go dashboard domain."
  value = var.enable_domain_mappings ? [
    for record in try(google_cloud_run_domain_mapping.go[0].status[0].resource_records, []) : {
      type  = record.type
      name  = record.name
      value = record.rrdata
    }
  ] : []
}

output "domain_mapping_status" {
  description = "Certificate/mapping conditions; all must be True before HTTPS is served."
  value = var.enable_domain_mappings ? {
    web = try(google_cloud_run_domain_mapping.web[0].status[0].conditions, [])
    go  = try(google_cloud_run_domain_mapping.go[0].status[0].conditions, [])
  } : {}
}

output "secret_ids" {
  description = "Secret Manager ids injected into python-backend."
  value       = { for key, secret in google_secret_manager_secret.secrets : key => secret.secret_id }
}

output "service_accounts" {
  description = "Runtime identities for the three Cloud Run services."
  value = {
    python = google_service_account.python.email
    web    = google_service_account.web.email
    go     = google_service_account.go.email
  }
}

output "deploy_commands" {
  description = "Copy/paste commands to redeploy images without Terraform."
  value = {
    python = "gcloud run deploy ${local.python_service} --image ${var.python_image} --region ${var.region} --project ${var.project_id}"
    web    = "gcloud run deploy ${local.web_service} --image ${var.web_image} --region ${var.region} --project ${var.project_id}"
    go     = "gcloud run deploy ${local.go_service} --image ${var.go_image} --region ${var.region} --project ${var.project_id}"
  }
}
