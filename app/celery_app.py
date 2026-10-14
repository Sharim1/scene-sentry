from datetime import timedelta

from celery import Celery

from app.config import settings
from app.utils.log_safety import quiet_http_client_logs

quiet_http_client_logs()

SOFT_LIMIT_FRACTION = 0.8
HARD_LIMIT_FRACTION = 0.9

PERIODIC_TASKS = {
    "content-discovery": (
        "app.tasks.periodic.content_discovery_task",
        timedelta(hours=settings.discovery_interval_hours),
    ),
    "content-enrichment": (
        "app.tasks.periodic.content_enrichment_task",
        timedelta(minutes=settings.enrichment_interval_minutes),
    ),
    "gossip-scraping": (
        "app.tasks.periodic.gossip_scraping_task",
        timedelta(minutes=settings.gossip_scrape_interval_minutes),
    ),
    "content-reranking": ("app.tasks.periodic.reranking_task", timedelta(minutes=settings.reranking_interval_minutes)),
    "send-reminders": ("app.tasks.periodic.reminder_task", timedelta(minutes=settings.reminder_check_interval_minutes)),
    "content-embedding": (
        "app.tasks.periodic.embedding_refresh_task",
        timedelta(minutes=settings.embedding_interval_minutes),
    ),
    "cleanup": ("app.tasks.periodic.cleanup_task", timedelta(hours=24)),
}

celery_app = Celery("scenesentry", include=["app.tasks.periodic"])

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        name: {"task": task, "schedule": interval, "options": {"expires": interval.total_seconds()}}
        for name, (task, interval) in PERIODIC_TASKS.items()
    },
    # Each task may run for at most 80% (soft) / 90% (hard) of its interval, so one
    # slow run can never outlast its schedule.
    task_annotations={
        task: {
            "soft_time_limit": int(interval.total_seconds() * SOFT_LIMIT_FRACTION),
            "time_limit": int(interval.total_seconds() * HARD_LIMIT_FRACTION),
        }
        for task, interval in PERIODIC_TASKS.values()
    },
)
