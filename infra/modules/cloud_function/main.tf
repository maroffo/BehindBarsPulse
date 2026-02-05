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

# Grant Cloud Build service account access to function source bucket
resource "google_storage_bucket_iam_member" "cloudbuild_gcs" {
  bucket = var.gcs_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# Grant Cloud Build service account Artifact Registry write access
resource "google_project_iam_member" "cloudbuild_artifact_registry" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# Grant default compute SA Cloud Build permissions (required for Gen 2 functions)
resource "google_project_iam_member" "compute_cloudbuild" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "compute_storage" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
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

# Get project number for service agent references
data "google_project" "project" {
  project_id = var.project_id
}

# Grant GCS service agent Pub/Sub publisher role (required for Eventarc GCS triggers)
# GCS service agent format: service-{PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com
resource "google_project_iam_member" "gcs_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.project.number}@gs-project-accounts.iam.gserviceaccount.com"
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

  depends_on = [
    google_project_iam_member.gcs_pubsub_publisher,
    google_project_iam_member.eventarc_gcs,
    google_secret_manager_secret_iam_member.function_db_password,
    google_storage_bucket_iam_member.cloudbuild_gcs,
    google_project_iam_member.cloudbuild_artifact_registry,
    google_project_iam_member.compute_cloudbuild,
    google_project_iam_member.compute_logs,
    google_project_iam_member.compute_storage,
  ]

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
      GCS_BUCKET          = var.gcs_bucket
      DB_HOST             = var.db_host
      DB_NAME             = var.db_name
      DB_USER             = var.db_user
      DB_PASSWORD_SECRET  = "${var.db_password_secret_name}/versions/latest"
    }

    vpc_connector                 = var.vpc_connector_id
    vpc_connector_egress_settings = "PRIVATE_RANGES_ONLY"
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.storage.object.v1.finalized"
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = google_service_account.function.email

    event_filters {
      attribute = "bucket"
      value     = var.gcs_bucket
    }
    # Note: Path filtering done in function code (lines 282-285)
    # GCS triggers don't support match-path-pattern operator
  }
}

# Allow Eventarc to invoke the Cloud Function (Gen2 functions are Cloud Run services)
resource "google_cloud_run_v2_service_iam_member" "eventarc_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.process_batch.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.function.email}"
}

output "function_name" {
  value = google_cloudfunctions2_function.process_batch.name
}

output "function_uri" {
  value = google_cloudfunctions2_function.process_batch.service_config[0].uri
}
