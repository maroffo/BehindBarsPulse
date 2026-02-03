# ABOUTME: AWS SES module for email sending infrastructure.
# ABOUTME: Creates domain verification, SMTP credentials, and IAM user.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "domain" {
  description = "Domain to verify for SES (e.g., behindbars.news)"
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region for SES"
  type        = string
  default     = "us-east-1"
}

# SES Domain Identity
resource "aws_ses_domain_identity" "main" {
  domain = var.domain
}

# SES Domain DKIM
resource "aws_ses_domain_dkim" "main" {
  domain = aws_ses_domain_identity.main.domain
}

# SES Domain Mail From (optional, for better deliverability)
resource "aws_ses_domain_mail_from" "main" {
  domain           = aws_ses_domain_identity.main.domain
  mail_from_domain = "mail.${var.domain}"
}

# IAM User for SMTP
resource "aws_iam_user" "ses_smtp" {
  name = "behindbars-${var.environment}-ses-smtp"
  path = "/system/"

  tags = {
    Environment = var.environment
    Purpose     = "SES SMTP credentials"
  }
}

# IAM Policy for SES sending
resource "aws_iam_user_policy" "ses_smtp" {
  name = "ses-send-email"
  user = aws_iam_user.ses_smtp.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ses:FromAddress" = [
              "*@${var.domain}"
            ]
          }
        }
      }
    ]
  })
}

# SMTP Credentials (Access Key)
resource "aws_iam_access_key" "ses_smtp" {
  user = aws_iam_user.ses_smtp.name
}

# Outputs
output "domain_verification_token" {
  description = "TXT record value for domain verification"
  value       = aws_ses_domain_identity.main.verification_token
}

output "dkim_tokens" {
  description = "CNAME records for DKIM (create 3 CNAME records)"
  value       = aws_ses_domain_dkim.main.dkim_tokens
}

output "mail_from_mx_record" {
  description = "MX record for mail-from domain"
  value       = "feedback-smtp.${var.aws_region}.amazonses.com"
}

output "mail_from_txt_record" {
  description = "SPF TXT record for mail-from domain"
  value       = "v=spf1 include:amazonses.com ~all"
}

output "smtp_username" {
  description = "SMTP username (AWS Access Key ID)"
  value       = aws_iam_access_key.ses_smtp.id
}

output "smtp_password" {
  description = "SMTP password (derived from secret key)"
  value       = aws_iam_access_key.ses_smtp.ses_smtp_password_v4
  sensitive   = true
}

output "smtp_endpoint" {
  description = "SES SMTP endpoint"
  value       = "email-smtp.${var.aws_region}.amazonaws.com"
}
