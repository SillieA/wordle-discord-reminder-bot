terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Bucket and region are supplied at `terraform init` time via -backend-config flags.
  # See the README for details.
  backend "s3" {
    key     = "wordle-discord-reminder-bot/terraform.tfstate"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
}
