variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run deployment"
  type        = string
  default     = "us-central1"
}

variable "billing_table" {
  description = "BigQuery billing export table (e.g., project.dataset.table_*)"
  type        = string
}

variable "cost_threshold" {
  description = "Daily cost threshold in USD to trigger alerts"
  type        = number
  default     = 100
}

variable "notification_email" {
  description = "Email address for cost alerts"
  type        = string
}

variable "schedule_timezone" {
  description = "Timezone for Cloud Scheduler (IANA format)"
  type        = string
  default     = "UTC"
}

variable "schedule_cron" {
  description = "Cron schedule for running the cost monitor"
  type        = string
  default     = "0 4 * * *" # 4 AM daily
}