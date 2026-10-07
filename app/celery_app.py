from datetime import timedelta

from celery import Celery

from app.config import settings

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
        "content-discovery": {
            "task": "app.tasks.periodic.content_discovery_task",
            "schedule": timedelta(hours=settings.discovery_interval_hours),
        },
        "content-enrichment": {
            "task": "app.tasks.periodic.content_enrichment_task",
            "schedule": timedelta(minutes=settings.enrichment_interval_minutes),
        },
        "gossip-scraping": {
            "task": "app.tasks.periodic.gossip_scraping_task",
            "schedule": timedelta(minutes=settings.gossip_scrape_interval_minutes),
        },
        "content-reranking": {
            "task": "app.tasks.periodic.reranking_task",
            "schedule": timedelta(minutes=settings.reranking_interval_minutes),
        },
        "send-reminders": {
            "task": "app.tasks.periodic.reminder_task",
            "schedule": timedelta(minutes=settings.reminder_check_interval_minutes),
        },
        "content-embedding": {
            "task": "app.tasks.periodic.embedding_refresh_task",
            "schedule": timedelta(minutes=settings.embedding_interval_minutes),
        },
        "cleanup": {
            "task": "app.tasks.periodic.cleanup_task",
            "schedule": timedelta(hours=24),
        },
    },
)
