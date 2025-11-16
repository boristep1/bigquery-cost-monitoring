import os
import datetime
from google.cloud import bigquery
from google.cloud import monitoring_v3
from google.protobuf.timestamp_pb2 import Timestamp
from google.api import metric_pb2 as ga_metric
from google.api import label_pb2 as ga_label
import logging
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
BILLING_TABLE = os.environ.get(
    "BILLING_TABLE",
    "your-project.your_dataset.gcp_billing_export_v1_*"
)
MONITORING_PROJECT_ID = os.environ.get("GCP_PROJECT")
CUSTOM_METRIC_TYPE = "custom.googleapis.com/billing/bigquery/daily_cost"
# --- End Configuration ---

# Initialize clients (reused across invocations)
bq_client = bigquery.Client()
monitoring_client = monitoring_v3.MetricServiceClient()


def ensure_metric_descriptor_exists():
    """
    Ensures the custom metric descriptor exists in Cloud Monitoring.
    Creates it if it doesn't exist.
    """
    project_name = f"projects/{MONITORING_PROJECT_ID}"
    
    try:
        metric_name = f"{project_name}/metricDescriptors/{CUSTOM_METRIC_TYPE}"
        monitoring_client.get_metric_descriptor(name=metric_name)
        logger.info(f"Metric descriptor {CUSTOM_METRIC_TYPE} already exists.")
        return
    except Exception:
        logger.info(f"Metric descriptor {CUSTOM_METRIC_TYPE} not found. Creating...")
    
    descriptor = ga_metric.MetricDescriptor()
    descriptor.type = CUSTOM_METRIC_TYPE
    descriptor.metric_kind = ga_metric.MetricDescriptor.MetricKind.GAUGE
    descriptor.value_type = ga_metric.MetricDescriptor.ValueType.DOUBLE
    descriptor.description = "Daily BigQuery cost per project in USD"
    descriptor.display_name = "BigQuery Daily Cost"
    
    project_label = ga_label.LabelDescriptor()
    project_label.key = "project_id"
    project_label.value_type = ga_label.LabelDescriptor.ValueType.STRING
    project_label.description = "GCP Project ID"
    descriptor.labels.append(project_label)
    
    try:
        monitoring_client.create_metric_descriptor(
            name=project_name,
            metric_descriptor=descriptor
        )
        logger.info(f"Created metric descriptor: {CUSTOM_METRIC_TYPE}")
    except Exception as e:
        logger.warning(f"Failed to create metric descriptor (may already exist): {e}")


def get_previous_day_range():
    """
    Calculate the UTC timestamp range for the previous day.
    Returns tuple of (start_datetime, end_datetime).
    """
    today = datetime.datetime.now(datetime.timezone.utc).date()
    yesterday = today - datetime.timedelta(days=1)
    start_time = datetime.datetime.combine(
        yesterday, 
        datetime.time.min, 
        tzinfo=datetime.timezone.utc
    )
    end_time = datetime.datetime.combine(
        today, 
        datetime.time.min, 
        tzinfo=datetime.timezone.utc
    )
    return start_time, end_time


def fetch_bigquery_costs(start_time, end_time):
    """
    Query billing export for BigQuery costs in the given time range.
    Uses parameterized query to prevent SQL injection.
    """
    query = """
        SELECT
            project.id AS project_id,
            SUM(cost) AS daily_cost
        FROM
            `{table}`
        WHERE
            service.description = 'BigQuery'
            AND usage_start_time >= @start_time
            AND usage_start_time < @end_time
            AND cost > 0
        GROUP BY
            project_id
        HAVING
            daily_cost > 0
    """.format(table=BILLING_TABLE)
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "start_time", 
                "TIMESTAMP", 
                start_time
            ),
            bigquery.ScalarQueryParameter(
                "end_time", 
                "TIMESTAMP", 
                end_time
            ),
        ]
    )
    
    logger.info(
        f"Querying billing data from {start_time.isoformat()} "
        f"to {end_time.isoformat()}"
    )
    
    query_job = bq_client.query(query, job_config=job_config)
    results = query_job.result()
    
    return list(results)


def create_time_series(project_id, daily_cost, timestamp):
    """
    Create a TimeSeries object for a single project's daily cost.
    """
    series = monitoring_v3.TimeSeries()
    series.metric.type = CUSTOM_METRIC_TYPE
    series.resource.type = "global"
    series.metric.labels["project_id"] = project_id
    
    point = monitoring_v3.Point()
    point.value.double_value = float(daily_cost)
    point.interval.end_time.CopyFrom(timestamp)
    
    series.points = [point]
    series.metric_kind = ga_metric.MetricDescriptor.MetricKind.GAUGE
    series.value_type = ga_metric.MetricDescriptor.ValueType.DOUBLE
    
    return series


def write_metrics_to_monitoring(time_series_list):
    """
    Write time series data to Cloud Monitoring in batches.
    """
    if not time_series_list:
        logger.info("No time series data to write.")
        return
    
    project_name = f"projects/{MONITORING_PROJECT_ID}"
    batch_size = 200
    
    for i in range(0, len(time_series_list), batch_size):
        batch = time_series_list[i:i + batch_size]
        try:
            monitoring_client.create_time_series(
                name=project_name,
                time_series=batch
            )
            logger.info(
                f"Successfully wrote batch of {len(batch)} time series "
                f"(total: {i + len(batch)}/{len(time_series_list)})"
            )
        except Exception as e:
            logger.error(f"Failed to write time series batch: {e}")
            failed_projects = [ts.metric.labels["project_id"] for ts in batch]
            logger.error(f"Failed projects: {failed_projects}")
            raise


@functions_framework.http
def main(request):
    """
    Cloud Run entry point. Fetches previous day's BigQuery cost
    per project and writes it to Cloud Monitoring.
    """
    try:
        logger.info("Starting BigQuery daily cost monitoring function")
        
        if not MONITORING_PROJECT_ID:
            raise ValueError("GCP_PROJECT environment variable not set")
        
        ensure_metric_descriptor_exists()
        start_time, end_time = get_previous_day_range()
        results = fetch_bigquery_costs(start_time, end_time)
        
        if not results:
            logger.info("No BigQuery costs found for the previous day")
            return ("No data to report", 200)
        
        metric_timestamp = Timestamp()
        metric_timestamp.FromDatetime(end_time)
        
        time_series_list = []
        for row in results:
            project_id = row.project_id
            daily_cost = row.daily_cost
            
            logger.info(f"Project: {project_id}, Cost: ${daily_cost:.2f}")
            
            series = create_time_series(project_id, daily_cost, metric_timestamp)
            time_series_list.append(series)
        
        write_metrics_to_monitoring(time_series_list)
        
        total_cost = sum(r.daily_cost for r in results)
        logger.info(
            f"Successfully processed {len(time_series_list)} projects. "
            f"Total cost: ${total_cost:.2f}"
        )
        
        return (
            f"Successfully wrote metrics for {len(time_series_list)} projects. "
            f"Total cost: ${total_cost:.2f}",
            200
        )
        
    except Exception as e:
        logger.error(f"Function failed with error: {e}", exc_info=True)
        return (f"Error: {str(e)}", 500)
