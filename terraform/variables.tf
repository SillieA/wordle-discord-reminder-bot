variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region to deploy into"
}

variable "function_name" {
  type        = string
  default     = "WordleReminderBot"
  description = "Name for the Lambda function and related resources"
}

variable "discord_token" {
  type        = string
  sensitive   = true
  description = "Discord bot token"
}

variable "channel_id" {
  type        = string
  description = "Discord channel ID where Wordle scores are posted"
}

variable "user_ids" {
  type        = string
  description = "Comma-separated Discord user IDs to track (e.g. \"111111,222222,333333\")"
}

variable "schedule" {
  type        = string
  default     = "cron(0 20 * * ? *)"
  description = "EventBridge schedule expression (default: 9 PM BST / 8 PM UTC daily)"
}

variable "debug_messages" {
  type        = string
  default     = "true"
  description = "When \"true\", logs the last 10 raw Discord messages as JSON to CloudWatch on each invocation. Useful for debugging message format issues."
}
