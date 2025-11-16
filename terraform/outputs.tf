output "service_account_email" {
  description = "Email of the Cloud Run service account"
  value       = google_service_account.cloud_run_sa.email
}

output "artifact_registry_url" {
  description = "URL of the Artifact Registry repository"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.cloud_run_images.repository_id}"
}

output "scheduler_job_name" {
  description = "Name of the Cloud Scheduler job"
  value       = google_cloud_scheduler_job.daily_trigger.name
}

output "alert_policy_name" {
  description = "Name of the alert policy"
  value       = google_monitoring_alert_policy.high_daily_cost.display_name
}

output "custom_metric_type" {
  description = "Custom metric type in Cloud Monitoring"
  value       = "custom.googleapis.com/billing/bigquery/daily_cost"
}

output "notification_channel_id" {
  description = "Notification channel ID"
  value       = google_monitoring_notification_channel.email.id
}