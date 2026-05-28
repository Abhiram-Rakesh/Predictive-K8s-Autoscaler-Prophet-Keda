terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # S3 native state locking (Terraform 1.10+) — no DynamoDB table needed.
  # Pass -backend-config="bucket=..." -backend-config="region=..." on init.
  backend "s3" {
    key          = "predictive-autoscaler-eks/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.aws_region
}
