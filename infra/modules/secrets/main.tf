# ABOUTME: Secret Manager module for sensitive credentials.
# ABOUTME: Stores database password, Gemini API key, and SES credentials.

terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)"
  type        = string
}

# Generate random password for database
resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

variable "gemini_api_key" {
  description = "Gemini API key"
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
  secret_data = random_password.db_password.result
}

# Gemini API key secret
resource "google_secret_manager_secret" "gemini_api_key" {
  project   = var.project_id
  secret_id = "behindbars-${var.environment}-gemini-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
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

output "db_password" {
  value     = random_password.db_password.result
  sensitive = true
}

output "db_password_secret_id" {
  value = google_secret_manager_secret.db_password.id
}

output "db_password_secret_name" {
  value = google_secret_manager_secret.db_password.name
}

output "gemini_api_key_secret_name" {
  value = google_secret_manager_secret.gemini_api_key.name
}

output "ses_username_secret_id" {
  value = var.ses_username != "" ? google_secret_manager_secret.ses_username[0].id : null
}

output "ses_password_secret_id" {
  value = var.ses_password != "" ? google_secret_manager_secret.ses_password[0].id : null
}
