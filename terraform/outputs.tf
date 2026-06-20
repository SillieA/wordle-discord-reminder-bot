output "lambda_function_arn" {
  description = "ARN of the Wordle Reminder Lambda function"
  value       = aws_lambda_function.wordle_reminder.arn
}

output "lambda_function_name" {
  description = "Name of the Wordle Reminder Lambda function"
  value       = aws_lambda_function.wordle_reminder.function_name
}
