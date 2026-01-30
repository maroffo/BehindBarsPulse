# ABOUTME: Cloud Storage module for backups and Terraform state.
# ABOUTME: Creates GCS buckets with appropriate lifecycle policies.

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

# Terraform state bucket
resource "google_storage_bucket" "tfstate" {
  name     = "${var.project_id}-behindbars-${var.environment}-tfstate"
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 5
    }
    action {
      type = "Delete"
    }
  }
}

# Backup bucket for database exports
resource "google_storage_bucket" "backups" {
  name     = "${var.project_id}-behindbars-${var.environment}-backups"
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# Assets bucket (newsletters, images)
resource "google_storage_bucket" "assets" {
  name     = "${var.project_id}-behindbars-${var.environment}-assets"
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true
}

output "tfstate_bucket" {
  value = google_storage_bucket.tfstate.name
}

output "backups_bucket" {
  value = google_storage_bucket.backups.name
}

output "assets_bucket" {
  value = google_storage_bucket.assets.name
}
