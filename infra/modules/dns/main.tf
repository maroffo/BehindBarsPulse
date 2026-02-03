# ABOUTME: Cloud DNS module for domain management.
# ABOUTME: Adds records to existing DNS zone for Cloud Run custom domain.

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "domain" {
  description = "Domain name (e.g., behindbars.news)"
  type        = string
}

variable "zone_name" {
  description = "Existing Cloud DNS zone name"
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)"
  type        = string
}

locals {
  # Cloud Run global IP addresses for custom domains
  cloud_run_ipv4 = [
    "216.239.32.21",
    "216.239.34.21",
    "216.239.36.21",
    "216.239.38.21",
  ]
  cloud_run_ipv6 = [
    "2001:4860:4802:32::15",
    "2001:4860:4802:34::15",
    "2001:4860:4802:36::15",
    "2001:4860:4802:38::15",
  ]
}

# Reference existing DNS zone
data "google_dns_managed_zone" "main" {
  name    = var.zone_name
  project = var.project_id
}

# A records for Cloud Run
resource "google_dns_record_set" "a" {
  name         = data.google_dns_managed_zone.main.dns_name
  managed_zone = data.google_dns_managed_zone.main.name
  project      = var.project_id
  type         = "A"
  ttl          = 300
  rrdatas      = local.cloud_run_ipv4
}

# AAAA records for Cloud Run
resource "google_dns_record_set" "aaaa" {
  name         = data.google_dns_managed_zone.main.dns_name
  managed_zone = data.google_dns_managed_zone.main.name
  project      = var.project_id
  type         = "AAAA"
  ttl          = 300
  rrdatas      = local.cloud_run_ipv6
}

# www CNAME to apex
resource "google_dns_record_set" "www" {
  name         = "www.${data.google_dns_managed_zone.main.dns_name}"
  managed_zone = data.google_dns_managed_zone.main.name
  project      = var.project_id
  type         = "CNAME"
  ttl          = 300
  rrdatas      = [data.google_dns_managed_zone.main.dns_name]
}

output "name_servers" {
  description = "Name servers for the domain"
  value       = data.google_dns_managed_zone.main.name_servers
}

output "zone_name" {
  description = "DNS zone name"
  value       = data.google_dns_managed_zone.main.name
}
