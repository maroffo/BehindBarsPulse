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

variable "cloud_run_service_name" {
  description = "Cloud Run service name"
  type        = string
}

variable "cloud_run_service_account" {
  description = "Cloud Run service account email"
  type        = string
}

variable "oidc_audience" {
  description = "OIDC token audience (custom domain URL or Cloud Run URL)"
  type        = string
  default     = ""
}

variable "timezone" {
  description = "Timezone for scheduler jobs"
  type        = string
  default     = "Europe/Rome"
}

locals {
  scheduler_name_prefix = "behindbars-${var.environment}"
  # Use custom domain as audience if provided, otherwise fall back to Cloud Run URL
  effective_audience = var.oidc_audience != "" ? var.oidc_audience : var.cloud_run_service_url
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
  name     = var.cloud_run_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# Article collection job (every 30 minutes)
# RSS feed limited to 15 articles, frequent collection prevents missing articles
resource "google_cloud_scheduler_job" "collect" {
  name        = "${local.scheduler_name_prefix}-collect"
  description = "Article collection from RSS feeds (every 30 min, dedup by URL)"
  project     = var.project_id
  region      = var.region
  schedule    = "*/30 * * * *"
  time_zone   = var.timezone

  http_target {
    uri         = "${var.cloud_run_service_url}/api/collect"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = local.effective_audience
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

# Daily newsletter batch job submission (10:00 AM Europe/Rome)
# Submits Vertex AI batch job for newsletter generation
# Results processed by Cloud Function when job completes
resource "google_cloud_scheduler_job" "generate" {
  name        = "${local.scheduler_name_prefix}-generate-batch"
  description = "Submit batch job for daily newsletter generation"
  project     = var.project_id
  region      = var.region
  schedule    = "0 10 * * *"
  time_zone   = var.timezone

  http_target {
    uri         = "${var.cloud_run_service_url}/api/generate-batch"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = local.effective_audience
    }
  }

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
    max_doublings        = 3
  }

  # Batch job submission is fast, processing happens async
  attempt_deadline = "120s"
}

# Daily bulletin job (10:00 AM Europe/Rome)
# Generates editorial commentary on previous day's articles
resource "google_cloud_scheduler_job" "bulletin" {
  name        = "bulletin-daily"
  description = "Daily editorial bulletin generation"
  project     = var.project_id
  region      = var.region
  schedule    = "0 10 * * *"
  time_zone   = var.timezone

  http_target {
    uri         = "${var.cloud_run_service_url}/api/bulletin"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = local.effective_audience
    }
  }

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
    max_backoff_duration = "600s"
    max_doublings        = 3
  }

  attempt_deadline = "600s"
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
      audience              = local.effective_audience
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

output "bulletin_job_name" {
  value = google_cloud_scheduler_job.bulletin.name
}
