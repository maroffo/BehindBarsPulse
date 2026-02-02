# ABOUTME: Cloud SQL PostgreSQL module with pgvector support.
# ABOUTME: Creates db-f1-micro instance with private IP and daily backups.

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

variable "vpc_id" {
  description = "VPC network ID for private IP"
  type        = string
}

variable "private_vpc_connection" {
  description = "Private VPC connection dependency"
  type        = string
}

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "behindbars"
}

variable "db_user" {
  description = "Database user"
  type        = string
  default     = "behindbars"
}

locals {
  instance_name = "behindbars-${var.environment}-db"
}

# Cloud SQL instance
resource "google_sql_database_instance" "main" {
  name             = local.instance_name
  project          = var.project_id
  region           = var.region
  database_version = "POSTGRES_15"

  depends_on = [var.private_vpc_connection]

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.vpc_id
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = false
      backup_retention_settings {
        retained_backups = 7
      }
    }

    database_flags {
      name  = "cloudsql.enable_pgvector"
      value = "on"
    }

    maintenance_window {
      day  = 7 # Sunday
      hour = 4
    }
  }

  deletion_protection = var.environment == "prod"
}

# Database
resource "google_sql_database" "main" {
  name     = var.db_name
  instance = google_sql_database_instance.main.name
  project  = var.project_id
}

# Database user
resource "google_sql_user" "main" {
  name     = var.db_user
  instance = google_sql_database_instance.main.name
  project  = var.project_id
  password = var.db_password
}

output "instance_name" {
  value = google_sql_database_instance.main.name
}

output "instance_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "private_ip" {
  value = google_sql_database_instance.main.private_ip_address
}

output "database_name" {
  value = google_sql_database.main.name
}

output "database_user" {
  value = google_sql_user.main.name
}
