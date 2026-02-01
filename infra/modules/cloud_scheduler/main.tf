# ABOUTME: Cloud Scheduler module for automated newsletter operations.
# ABOUTME: Configures daily collect/generate and weekly send jobs with OIDC authentication.

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

variable "cloud_run_service_url" {
  description = "Cloud Run service URL"
  type        = string
}

variable "cloud_run_service_account" {
  description = "Cloud Run service account email"
  type        = string
}

variable "timezone" {
  description = "Timezone for scheduler jobs"
  type        = string
  default     = "Europe/Rome"
}

locals {
  scheduler_name_prefix = "behindbars-${var.environment}"
}

# Service account for Cloud Scheduler
resource "google_service_account" "scheduler" {
  account_id   = "${local.scheduler_name_prefix}-scheduler"
  project      = var.project_id
  display_name = "BehindBars ${var.environment} Cloud Scheduler Service Account"
}

# Grant Cloud Scheduler SA permission to invoke Cloud Run
resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = split("/", var.cloud_run_service_url)[length(split("/", var.cloud_run_service_url)) - 1]
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# Daily article collection job (6:00 AM Europe/Rome)
resource "google_cloud_scheduler_job" "collect" {
  name        = "${local.scheduler_name_prefix}-collect"
  description = "Daily article collection from RSS feeds"
  project     = var.project_id
  region      = var.region
  schedule    = "0 6 * * *"
  time_zone   = var.timezone

  http_target {
    uri         = "${var.cloud_run_service_url}/api/collect"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = var.cloud_run_service_url
    }
  }

  retry_config {
    retry_count          = 3
    min_backoff_duration = "30s"
    max_backoff_duration = "300s"
    max_doublings        = 3
  }

  attempt_deadline = "600s"
}

# Daily newsletter generation job (7:00 AM Europe/Rome)
resource "google_cloud_scheduler_job" "generate" {
  name        = "${local.scheduler_name_prefix}-generate"
  description = "Daily newsletter generation (archive only, no send)"
  project     = var.project_id
  region      = var.region
  schedule    = "0 7 * * *"
  time_zone   = var.timezone

  http_target {
    uri         = "${var.cloud_run_service_url}/api/generate"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = var.cloud_run_service_url
    }
  }

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
    max_doublings        = 3
  }

  attempt_deadline = "1200s"
}

# Weekly digest job (Sunday 8:00 AM Europe/Rome)
resource "google_cloud_scheduler_job" "weekly" {
  name        = "${local.scheduler_name_prefix}-weekly"
  description = "Weekly digest generation and send to subscribers"
  project     = var.project_id
  region      = var.region
  schedule    = "0 8 * * 0"
  time_zone   = var.timezone

  http_target {
    uri         = "${var.cloud_run_service_url}/api/weekly"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = var.cloud_run_service_url
    }
  }

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
    max_doublings        = 3
  }

  attempt_deadline = "1800s"
}

output "scheduler_service_account" {
  value = google_service_account.scheduler.email
}

output "collect_job_name" {
  value = google_cloud_scheduler_job.collect.name
}

output "generate_job_name" {
  value = google_cloud_scheduler_job.generate.name
}

output "weekly_job_name" {
  value = google_cloud_scheduler_job.weekly.name
}
