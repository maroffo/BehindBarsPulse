# ABOUTME: Production environment Terraform configuration.
# ABOUTME: Deploys BehindBars infrastructure to GCP with production settings.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Configure backend after first apply
  # backend "gcs" {
  #   bucket = "PROJECT_ID-behindbars-prod-tfstate"
  #   prefix = "terraform/state"
  # }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
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

variable "container_image" {
  description = "Container image URL for Cloud Run"
  type        = string
}

variable "custom_domain" {
  description = "Custom domain (e.g., behindbars.org)"
  type        = string
  default     = ""
}

locals {
  environment = "prod"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "sqladmin.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
    "cloudscheduler.googleapis.com",
  ])

  project = var.project_id
  service = each.key

  disable_on_destroy = false
}

# Storage
module "storage" {
  source = "../../modules/storage"

  project_id  = var.project_id
  region      = var.region
  environment = local.environment
}

# Networking
module "networking" {
  source = "../../modules/networking"

  project_id  = var.project_id
  region      = var.region
  environment = local.environment

  depends_on = [google_project_service.apis]
}

# Secrets (generates db_password automatically)
module "secrets" {
  source = "../../modules/secrets"

  project_id     = var.project_id
  environment    = local.environment
  gemini_api_key = var.gemini_api_key
  ses_username   = var.ses_username
  ses_password   = var.ses_password

  depends_on = [google_project_service.apis]
}

# Cloud SQL
module "cloud_sql" {
  source = "../../modules/cloud_sql"

  project_id             = var.project_id
  region                 = var.region
  environment            = local.environment
  vpc_id                 = module.networking.vpc_id
  private_vpc_connection = module.networking.private_vpc_connection
  db_password            = module.secrets.db_password

  depends_on = [module.networking, module.secrets]
}

# Cloud Run
module "cloud_run" {
  source = "../../modules/cloud_run"

  project_id                 = var.project_id
  region                     = var.region
  environment                = local.environment
  image                      = var.container_image
  vpc_connector_id           = module.networking.vpc_connector_id
  cloud_sql_connection_name  = module.cloud_sql.instance_connection_name
  db_host                    = module.cloud_sql.private_ip
  db_name                    = module.cloud_sql.database_name
  db_user                    = module.cloud_sql.database_user
  db_password_secret_name    = module.secrets.db_password_secret_name
  gemini_api_key_secret_name = module.secrets.gemini_api_key_secret_name
  custom_domain              = var.custom_domain

  min_instances = 0 # Scale to zero (cost optimization)
  max_instances = 3

  depends_on = [module.cloud_sql, module.secrets]
}

# Cloud Scheduler
module "cloud_scheduler" {
  source = "../../modules/cloud_scheduler"

  project_id                = var.project_id
  region                    = var.region
  environment               = local.environment
  cloud_run_service_url     = module.cloud_run.service_url
  cloud_run_service_account = module.cloud_run.service_account_email

  depends_on = [google_project_service.apis, module.cloud_run]
}

output "cloud_sql_instance" {
  value = module.cloud_sql.instance_connection_name
}

output "cloud_sql_private_ip" {
  value     = module.cloud_sql.private_ip
  sensitive = true
}

output "service_url" {
  value = module.cloud_run.service_url
}

output "tfstate_bucket" {
  value = module.storage.tfstate_bucket
}

output "scheduler_service_account" {
  value = module.cloud_scheduler.scheduler_service_account
}
