# ABOUTME: AWS production environment for SES email infrastructure.
# ABOUTME: Separate from GCP infrastructure, manages email sending only.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment after first apply to store state remotely
  # backend "s3" {
  #   bucket = "behindbars-terraform-state"
  #   key    = "aws/prod/terraform.tfstate"
  #   region = "eu-west-1"
  # }
}

variable "aws_region" {
  description = "AWS region for SES"
  type        = string
  default     = "eu-west-1"
}

variable "domain" {
  description = "Domain for email sending"
  type        = string
}

locals {
  environment = "prod"
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "behindbars"
      Environment = local.environment
      ManagedBy   = "terraform"
    }
  }
}

module "ses" {
  source = "../../modules/aws_ses"

  domain      = var.domain
  environment = local.environment
  aws_region  = var.aws_region
}

# Outputs for DNS configuration
output "dns_records_required" {
  description = "DNS records to add to your domain"
  value = {
    # Domain verification
    verification = {
      type  = "TXT"
      name  = "_amazonses.${var.domain}"
      value = module.ses.domain_verification_token
    }

    # DKIM records (3 CNAME records)
    dkim = [
      for token in module.ses.dkim_tokens : {
        type  = "CNAME"
        name  = "${token}._domainkey.${var.domain}"
        value = "${token}.dkim.amazonses.com"
      }
    ]

    # Mail-from records
    mail_from_mx = {
      type     = "MX"
      name     = "mail.${var.domain}"
      value    = module.ses.mail_from_mx_record
      priority = 10
    }

    mail_from_spf = {
      type  = "TXT"
      name  = "mail.${var.domain}"
      value = module.ses.mail_from_txt_record
    }
  }
}

output "smtp_credentials" {
  description = "SMTP credentials for application"
  sensitive   = true
  value = {
    host     = module.ses.smtp_endpoint
    port     = 587
    username = module.ses.smtp_username
    password = module.ses.smtp_password
  }
}

output "smtp_username" {
  description = "SMTP username (safe to display)"
  value       = module.ses.smtp_username
}
