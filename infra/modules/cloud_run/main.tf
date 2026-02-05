# ABOUTME: Cloud Run service module for web application deployment.
# ABOUTME: Configures scale-to-zero, Cloud SQL connection, and custom domain.

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)"
  type        = string
}

variable "image" {
  description = "Container image URL"
  type        = string
}

variable "vpc_connector_id" {
  description = "VPC connector ID for Cloud SQL access"
  type        = string
}

variable "cloud_sql_connection_name" {
  description = "Cloud SQL instance connection name"
  type        = string
}

variable "db_host" {
  description = "Database host (private IP)"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "db_user" {
  description = "Database user"
  type        = string
}

variable "db_password_secret_name" {
  description = "Secret Manager secret name for database password"
  type        = string
}

variable "gemini_api_key_secret_name" {
  description = "Secret Manager secret name for Gemini API key"
  type        = string
}

variable "ses_username_secret_name" {
  description = "Secret Manager secret name for SES username (optional)"
  type        = string
  default     = ""
}

variable "ses_password_secret_name" {
  description = "Secret Manager secret name for SES password (optional)"
  type        = string
  default     = ""
}

variable "custom_domain" {
  description = "Custom domain for the service (optional)"
  type        = string
  default     = ""
}

variable "gcs_bucket" {
  description = "GCS bucket for persistent storage (optional)"
  type        = string
  default     = ""
}

variable "min_instances" {
  description = "Minimum number of instances (0 for scale to zero)"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of instances"
  type        = number
  default     = 2
}

locals {
  service_name = "behindbars-${var.environment}"
}

# Get project number for Cloud Run URL
data "google_project" "project" {
  project_id = var.project_id
}

# Service account for Cloud Run
resource "google_service_account" "cloud_run" {
  account_id   = "${local.service_name}-sa"
  project      = var.project_id
  display_name = "BehindBars ${var.environment} Cloud Run Service Account"
}

# Grant Secret Manager access for DB password
resource "google_secret_manager_secret_iam_member" "db_password_access" {
  project   = var.project_id
  secret_id = var.db_password_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Grant Secret Manager access for Gemini API key
resource "google_secret_manager_secret_iam_member" "gemini_api_key_access" {
  project   = var.project_id
  secret_id = var.gemini_api_key_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Grant Secret Manager access for SES username (optional)
resource "google_secret_manager_secret_iam_member" "ses_username_access" {
  count     = var.ses_username_secret_name != "" ? 1 : 0
  project   = var.project_id
  secret_id = var.ses_username_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Grant Secret Manager access for SES password (optional)
resource "google_secret_manager_secret_iam_member" "ses_password_access" {
  count     = var.ses_password_secret_name != "" ? 1 : 0
  project   = var.project_id
  secret_id = var.ses_password_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Grant Cloud SQL client access
resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Grant GCS bucket access (if configured)
resource "google_storage_bucket_iam_member" "assets_access" {
  count  = var.gcs_bucket != "" ? 1 : 0
  bucket = var.gcs_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Grant Vertex AI access for batch inference
resource "google_project_iam_member" "aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Cloud Run service
resource "google_cloud_run_v2_service" "main" {
  name     = local.service_name
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.cloud_run.email
    timeout         = "900s" # 15 minutes for newsletter generation

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = true
      }

      env {
        name  = "DB_HOST"
        value = var.db_host
      }

      env {
        name  = "DB_NAME"
        value = var.db_name
      }

      env {
        name  = "DB_USER"
        value = var.db_user
      }

      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.db_password_secret_name
            version = "latest"
          }
        }
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = var.gemini_api_key_secret_name
            version = "latest"
          }
        }
      }

      # Web / API settings for subscription flow and OIDC
      # APP_BASE_URL uses custom domain if provided, otherwise Cloud Run default URL pattern
      env {
        name  = "APP_BASE_URL"
        value = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${local.service_name}-${data.google_project.project.number}.${var.region}.run.app"
      }

      # SCHEDULER_AUDIENCE for OIDC token verification (dynamic like APP_BASE_URL)
      env {
        name  = "SCHEDULER_AUDIENCE"
        value = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${local.service_name}-${data.google_project.project.number}.${var.region}.run.app"
      }

      # GCS bucket for persistent storage
      env {
        name  = "GCS_BUCKET"
        value = var.gcs_bucket
      }

      # Google Project ID and Region for Vertex AI Batch
      env {
        name  = "GOOGLE_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_REGION"
        value = var.region
      }

      # SES credentials for email sending (optional)
      dynamic "env" {
        for_each = var.ses_username_secret_name != "" ? [1] : []
        content {
          name = "SES_USR"
          value_source {
            secret_key_ref {
              secret  = var.ses_username_secret_name
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = var.ses_password_secret_name != "" ? [1] : []
        content {
          name = "SES_PWD"
          value_source {
            secret_key_ref {
              secret  = var.ses_password_secret_name
              version = "latest"
            }
          }
        }
      }

      ports {
        container_port = 8000
      }

      startup_probe {
        http_get {
          path = "/api/health"
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/api/health"
        }
        period_seconds = 30
      }
    }

    annotations = {
      "run.googleapis.com/cloudsql-instances" = var.cloud_sql_connection_name
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Allow unauthenticated access
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.main.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Custom domain mapping (optional)
resource "google_cloud_run_domain_mapping" "custom" {
  count    = var.custom_domain != "" ? 1 : 0
  location = var.region
  project  = var.project_id
  name     = var.custom_domain

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.main.name
  }
}

output "service_url" {
  value = google_cloud_run_v2_service.main.uri
}

output "service_name" {
  value = google_cloud_run_v2_service.main.name
}

output "service_account_email" {
  value = google_service_account.cloud_run.email
}
