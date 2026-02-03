# ABOUTME: Cloud Function module for batch job result processing.
# ABOUTME: Event-driven architecture using GCS Object Finalize trigger.

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

variable "gcs_bucket" {
  description = "GCS bucket for assets (newsletter storage)"
  type        = string
}

variable "db_host" {
  description = "Database host"
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
  description = "Secret Manager secret name for DB password"
  type        = string
}

variable "vpc_connector_id" {
  description = "VPC connector for Cloud SQL access"
  type        = string
}

variable "function_source_bucket" {
  description = "GCS bucket for function source code"
  type        = string
}

locals {
  function_name = "behindbars-${var.environment}-process-batch"
  sa_name       = "behindbars-${var.environment}-fn"
}

# Service account for Cloud Function
resource "google_service_account" "function" {
  account_id   = local.sa_name
  project      = var.project_id
  display_name = "BehindBars ${var.environment} Cloud Function Service Account"
}

# Grant function SA access to GCS bucket
resource "google_storage_bucket_iam_member" "function_gcs" {
  bucket = var.gcs_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.function.email}"
}

# Grant function SA access to Secret Manager
resource "google_secret_manager_secret_iam_member" "function_db_password" {
  project   = var.project_id
  secret_id = var.db_password_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.function.email}"
}

# Grant Eventarc permission to receive events from GCS
# Required for GCS triggers to work
resource "google_project_iam_member" "eventarc_gcs" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.function.email}"
}

# Upload function source to GCS
resource "google_storage_bucket_object" "function_source" {
  name   = "functions/process-batch-${filemd5("${path.module}/../../../functions/process-batch/main.py")}.zip"
  bucket = var.function_source_bucket
  source = data.archive_file.function_source.output_path
}

data "archive_file" "function_source" {
  type        = "zip"
  output_path = "${path.module}/process-batch.zip"
  source_dir  = "${path.module}/../../../functions/process-batch"
}

# Cloud Function (2nd gen) triggered by GCS Object Finalize
# When Vertex AI batch job completes, it writes .jsonl results to the output bucket
# This trigger fires when any file is created in batch_jobs/*/output/
resource "google_cloudfunctions2_function" "process_batch" {
  name     = local.function_name
  project  = var.project_id
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "process_batch_results"

    source {
      storage_source {
        bucket = var.function_source_bucket
        object = google_storage_bucket_object.function_source.name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    min_instance_count    = 0
    available_memory      = "512M"
    timeout_seconds       = 300
    service_account_email = google_service_account.function.email

    environment_variables = {
      GCS_BUCKET = var.gcs_bucket
      DB_HOST    = var.db_host
      DB_NAME    = var.db_name
      DB_USER    = var.db_user
    }

    secret_environment_variables {
      key        = "DB_PASSWORD"
      project_id = var.project_id
      secret     = var.db_password_secret_name
      version    = "latest"
    }

    vpc_connector                 = var.vpc_connector_id
    vpc_connector_egress_settings = "PRIVATE_RANGES_ONLY"
  }

  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.storage.object.v1.finalized"
    retry_policy   = "RETRY_POLICY_RETRY"

    event_filters {
      attribute = "bucket"
      value     = var.gcs_bucket
    }

    # Only trigger on batch job output files (JSONL results)
    event_filters {
      attribute = "name"
      value     = "batch_jobs/*/output/*.jsonl"
      operator  = "match-path-pattern"
    }
  }
}

output "function_name" {
  value = google_cloudfunctions2_function.process_batch.name
}

output "function_uri" {
  value = google_cloudfunctions2_function.process_batch.service_config[0].uri
}
