from prometheus_client import Counter, Histogram, Gauge, Summary, Info
import time

# User metrics
user_creation_total = Counter(
    'cosap_user_creation_total',
    'Total number of users created'
)

user_login_total = Counter(
    'cosap_user_login_total', 
    'Total number of user logins',
    ['status', 'user_type']  # success/failure, admin/regular
)

# Project lifecycle metrics
project_creation_total = Counter(
    'cosap_project_creation_total',
    'Total number of projects created',
    ['status', 'user_type']  # draft/active, admin/regular
)

project_status_changes_total = Counter(
    'cosap_project_status_changes_total',
    'Total number of project status changes',
    ['from_status', 'to_status']
)

project_deletion_total = Counter(
    'cosap_project_deletion_total',
    'Total number of projects deleted'
)

# File processing metrics
file_upload_total = Counter(
    'cosap_file_upload_total',
    'Total number of files uploaded',
    ['file_extension', 'file_type']  # vcf/fastq/etc
)

file_deletion_total = Counter(
    'cosap_file_deletion_total',
    'Total number of files deleted'
)

file_processing_duration = Histogram(
    'cosap_file_processing_duration_seconds',
    'Time spent processing files',
    ['processing_type'],  # upload/validation/parsing
    buckets=[0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, float('inf')]
)

temp_upload_completion_total = Counter(
    'cosap_temp_upload_completion_total',
    'Total number of completed temporary uploads',
    ['status']  # success/failure
)

# COSAP job metrics - enhanced for Grafana
cosap_dna_job_submissions_total = Counter(
    'cosap_dna_job_submissions_total',
    'Total number of COSAP DNA job submissions',
    ['status', 'project_type']  # submitted/skipped/failed, research/clinical
)

cosap_parse_job_submissions_total = Counter(
    'cosap_parse_job_submissions_total',
    'Total number of COSAP parse job submissions',
    ['status']  # success/failure
)

cosap_annotation_job_submissions_total = Counter(
    'cosap_annotation_job_submissions_total',
    'Total number of COSAP annotation job submissions',
    ['status']  # success/failure
)

# Job duration metrics for performance monitoring
cosap_job_duration = Histogram(
    'cosap_job_duration_seconds',
    'Duration of COSAP jobs',
    ['job_type'],  # dna/parse/annotation
    buckets=[10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, float('inf')]
)

# Queue metrics for operational dashboards
cosap_queue_size = Gauge(
    'cosap_queue_size',
    'Number of jobs in queue',
    ['queue_name']  # dna/parse/annotation
)

cosap_active_workers = Gauge(
    'cosap_active_workers',
    'Number of active Celery workers',
    ['worker_type']
)

# Current state metrics (perfect for Grafana gauges)
active_projects_count = Gauge(
    'cosap_active_projects_count',
    'Current number of active projects',
    ['project_type']
)

active_users_count = Gauge(
    'cosap_active_users_count',
    'Current number of active users (logged in last 24h)'
)

pending_jobs_count = Gauge(
    'cosap_pending_jobs_count',
    'Current number of pending COSAP jobs',
    ['job_type']
)

# Report and analysis metrics
report_creation_total = Counter(
    'cosap_report_creation_total',
    'Total number of reports created',
    ['report_type']
)

variant_analysis_total = Counter(
    'cosap_variant_analysis_total',
    'Total number of variants analyzed',
    ['variant_type']  # snv/indel/cnv
)

# Error tracking for debugging dashboards
task_errors_total = Counter(
    'cosap_task_errors_total',
    'Total number of task errors',
    ['task_type', 'error_type']
)

# Performance metrics
api_request_duration = Histogram(
    'cosap_api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint', 'status_code'],
    buckets=[0.001, 0.01, 0.1, 0.5, 1, 2.5, 5, 10, float('inf')]
)

database_query_duration = Histogram(
    'cosap_database_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    buckets=[0.001, 0.01, 0.1, 0.5, 1, 2.5, 5, float('inf')]
)

# System resource metrics
memory_usage_bytes = Gauge(
    'cosap_memory_usage_bytes',
    'Memory usage in bytes',
    ['component']  # django/celery/redis
)

disk_usage_bytes = Gauge(
    'cosap_disk_usage_bytes',
    'Disk usage in bytes',
    ['mount_point', 'usage_type']  # used/available
)