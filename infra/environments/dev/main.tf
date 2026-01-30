# ABOUTME: Development environment Terraform configuration.
# ABOUTME: Deploys BehindBars infrastructure to GCP dev environment.

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
  #   bucket = "PROJECT_ID-behindbars-dev-tfstate"
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

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "container_image" {
  description = "Container image URL for Cloud Run"
  type        = string
  default     = ""
}

locals {
  environment = "dev"
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
    "aiplatform.googleapis.com",
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

# Secrets
module "secrets" {
  source = "../../modules/secrets"

  project_id  = var.project_id
  environment = local.environment
  db_password = var.db_password

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
  db_password            = var.db_password

  depends_on = [module.networking]
}

# Cloud Run (only if image provided)
module "cloud_run" {
  count  = var.container_image != "" ? 1 : 0
  source = "../../modules/cloud_run"

  project_id                = var.project_id
  region                    = var.region
  environment               = local.environment
  image                     = var.container_image
  vpc_connector_id          = module.networking.vpc_connector_id
  cloud_sql_connection_name = module.cloud_sql.instance_connection_name
  db_host                   = module.cloud_sql.private_ip
  db_name                   = module.cloud_sql.database_name
  db_user                   = module.cloud_sql.database_user
  db_password_secret_name   = module.secrets.db_password_secret_name

  min_instances = 0  # Scale to zero in dev
  max_instances = 2

  depends_on = [module.cloud_sql, module.secrets]
}

output "cloud_sql_instance" {
  value = module.cloud_sql.instance_connection_name
}

output "cloud_sql_private_ip" {
  value = module.cloud_sql.private_ip
}

output "service_url" {
  value = var.container_image != "" ? module.cloud_run[0].service_url : null
}

output "tfstate_bucket" {
  value = module.storage.tfstate_bucket
}
