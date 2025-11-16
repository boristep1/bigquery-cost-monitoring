# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "monitoring.googleapis.com",
    "bigquery.googleapis.com",
    "artifactregistry.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# Create Artifact Registry repository for Cloud Run images
resource "google_artifact_registry_repository" "cloud_run_images" {
  location      = var.region
  repository_id = "cloud-run-images"
  description   = "Docker repository for Cloud Run services"
  format        = "DOCKER"

  depends_on = [google_project_service.required_apis]
}

# Service account for Cloud Run
resource "google_service_account" "cloud_run_sa" {
  account_id   = "bq-cost-monitor"
  display_name = "BigQuery Cost Monitor Service Account"
  description  = "Service account for BigQuery cost monitoring Cloud Run function"
}

# IAM permissions for service account
resource "google_project_iam_member" "bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "bigquery_data_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "monitoring_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Cloud Build trigger for automatic deployment from GitHub
resource "google_cloudbuild_trigger" "deploy_trigger" {
  name        = "deploy-bq-cost-monitor"
  description = "Deploy BigQuery cost monitor on push to main branch"

  github {
    owner = "YOUR_GITHUB_USERNAME" # TODO: Update this
    name  = "bigquery-cost-monitoring" # TODO: Update this
    push {
      branch = "^main$"
    }
  }

  filename = "cloudbuild.yaml"

  substitutions = {
    _REGION          = var.region
    _REPOSITORY      = google_artifact_registry_repository.cloud_run_images.repository_id
    _SERVICE_NAME    = "bigquery-cost-monitor"
    _SERVICE_ACCOUNT = google_service_account.cloud_run_sa.email
    _BILLING_TABLE   = var.billing_table
  }

  depends_on = [google_project_service.required_apis]
}

# Service account for Cloud Scheduler
resource "google_service_account" "scheduler_sa" {
  account_id   = "bq-cost-scheduler"
  display_name = "Cloud Scheduler SA for BQ Cost Monitor"
}

# Allow scheduler to invoke Cloud Run
resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  service  = "bigquery-cost-monitor"
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_sa.email}"

  # Note: This assumes Cloud Run service already exists from Cloud Build
  # For initial setup, you may need to comment this out and apply in two stages
}

# Cloud Scheduler job to trigger daily
resource "google_cloud_scheduler_job" "daily_trigger" {
  name             = "bq-cost-monitor-daily"
  description      = "Trigger BigQuery cost monitoring daily"
  schedule         = var.schedule_cron
  time_zone        = var.schedule_timezone
  attempt_deadline = "320s"
  region           = var.region

  http_target {
    http_method = "POST"
    uri         = "https://bigquery-cost-monitor-${data.google_project.project.number}.${var.region}.run.app"

    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [google_project_service.required_apis]
}

# Data source for project number
data "google_project" "project" {
  project_id = var.project_id
}

# Notification channel for alerts
resource "google_monitoring_notification_channel" "email" {
  display_name = "BigQuery Cost Alert Email"
  type         = "email"

  labels = {
    email_address = var.notification_email
  }

  depends_on = [google_project_service.required_apis]
}

# Alert policy for high daily costs
resource "google_monitoring_alert_policy" "high_daily_cost" {
  display_name = "BigQuery Daily Cost Exceeds Threshold"
  combiner     = "OR"

  conditions {
    display_name = "Daily cost > $${var.cost_threshold}"

    condition_threshold {
      filter          = "resource.type = \"global\" AND metric.type = \"custom.googleapis.com/billing/bigquery/daily_cost\""
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = var.cost_threshold

      aggregations {
        alignment_period   = "86400s" # 1 day
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email.id
  ]

  alert_strategy {
    auto_close = "86400s" # Auto-close after 1 day
  }

  documentation {
    content = <<-EOT
      BigQuery daily cost has exceeded $${var.cost_threshold}.
      
      Check the Cloud Monitoring dashboard for per-project breakdown.
      Review recent queries in BigQuery audit logs to identify high-cost operations.
    EOT
  }

  depends_on = [google_project_service.required_apis]
}