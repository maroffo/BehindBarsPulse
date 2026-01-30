# ABOUTME: Secret Manager module for sensitive credentials.
# ABOUTME: Stores database password and SES credentials.

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)"
  type        = string
}

variable "db_password" {
  description = "Database password to store"
  type        = string
  sensitive   = true
}

variable "ses_username" {
  description = "AWS SES SMTP username"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ses_password" {
  description = "AWS SES SMTP password"
  type        = string
  sensitive   = true
  default     = ""
}

# Database password secret
resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = "behindbars-${var.environment}-db-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = var.db_password
}

# SES username secret (optional)
resource "google_secret_manager_secret" "ses_username" {
  count     = var.ses_username != "" ? 1 : 0
  project   = var.project_id
  secret_id = "behindbars-${var.environment}-ses-username"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "ses_username" {
  count       = var.ses_username != "" ? 1 : 0
  secret      = google_secret_manager_secret.ses_username[0].id
  secret_data = var.ses_username
}

# SES password secret (optional)
resource "google_secret_manager_secret" "ses_password" {
  count     = var.ses_password != "" ? 1 : 0
  project   = var.project_id
  secret_id = "behindbars-${var.environment}-ses-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "ses_password" {
  count       = var.ses_password != "" ? 1 : 0
  secret      = google_secret_manager_secret.ses_password[0].id
  secret_data = var.ses_password
}

output "db_password_secret_id" {
  value = google_secret_manager_secret.db_password.id
}

output "db_password_secret_name" {
  value = google_secret_manager_secret.db_password.name
}

output "ses_username_secret_id" {
  value = var.ses_username != "" ? google_secret_manager_secret.ses_username[0].id : null
}

output "ses_password_secret_id" {
  value = var.ses_password != "" ? google_secret_manager_secret.ses_password[0].id : null
}
