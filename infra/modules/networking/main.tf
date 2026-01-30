# ABOUTME: VPC and networking module for private Cloud SQL access.
# ABOUTME: Creates VPC, subnet, and serverless VPC connector.

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

# VPC Network
resource "google_compute_network" "main" {
  name                    = "behindbars-${var.environment}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
}

# Subnet for Cloud SQL and services
resource "google_compute_subnetwork" "main" {
  name          = "behindbars-${var.environment}-subnet"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.main.id
  ip_cidr_range = "10.0.0.0/24"

  private_ip_google_access = true
}

# Private IP range for Cloud SQL
resource "google_compute_global_address" "private_ip_range" {
  name          = "behindbars-${var.environment}-private-ip"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}

# Private services connection
resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# Serverless VPC Connector for Cloud Run → Cloud SQL
resource "google_vpc_access_connector" "connector" {
  name          = "behindbars-${var.environment}-connector"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.main.name
  ip_cidr_range = "10.8.0.0/28"

  min_instances = 2
  max_instances = 3
}

output "vpc_id" {
  value = google_compute_network.main.id
}

output "vpc_name" {
  value = google_compute_network.main.name
}

output "subnet_id" {
  value = google_compute_subnetwork.main.id
}

output "vpc_connector_id" {
  value = google_vpc_access_connector.connector.id
}

output "private_vpc_connection" {
  value = google_service_networking_connection.private_vpc_connection.id
}
