import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.celery_app import celery_app
from app.database import db_session
from app.models import Gossip, Notification, Reminder, User
from app.repositories.library_repo import LibraryRepository
from app.services.content_discovery import ContentDiscoveryService
from app.services.gossip_service import GossipService
from app.services.ranking_service import RankingService
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def content_discovery_task(self):
    try:
        with db_session() as db:
            svc = ContentDiscoveryService(db)
            if svc.is_catalog_empty():
                total = svc.seed_catalog()
                logger.info("Seed complete: %d items", total)
            else:
                result = svc.run_scheduled_sync()
                logger.info("Sync: %d movies, %d TV shows", result["movies"], result["tv_shows"])
            enriched = svc.enrich_sparse_content(batch_size=30)
            if enriched:
                logger.info("Enrichment: %d records", enriched)
    except Exception as exc:
        logger.error("content_discovery_task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def content_enrichment_task(self):
    try:
        with db_session() as db:
            svc = ContentDiscoveryService(db)
            enriched = svc.enrich_sparse_content(batch_size=50)
            logger.info("Enrichment: %d records", enriched)
    except Exception as exc:
        logger.error("content_enrichment_task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def gossip_scraping_task(self):
    try:
        with db_session() as db:
            tracked = LibraryRepository(db).get_all_tracked_titles()
        svc = GossipService()
        results = asyncio.run(svc.scrape_latest(tracked[:20]))
        logger.info("Gossip: %d items scraped", len(results))
    except Exception as exc:
        logger.error("gossip_scraping_task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def reranking_task(self):
    try:
        with db_session() as db:
            users = db.query(User).all()
            for user in users:
                try:
                    svc = RankingService(db)
                    count = asyncio.run(svc.run_reranking(user.id))
                    logger.info("Re-rank %s: %d items", user.username, count)
                except Exception as e:
                    logger.error("Re-rank error for %s: %s", user.username, e)
    except Exception as exc:
        logger.error("reranking_task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def reminder_task(self):
    try:
        with db_session() as db:
            svc = ReminderService(db)
            count = svc.process_due_reminders()
            logger.info("Reminders: %d processed", count)
    except Exception as exc:
        logger.error("reminder_task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def embedding_refresh_task(self):
    try:
        from app.services.embedding_service import EmbeddingService

        with db_session() as db:
            svc = EmbeddingService(db)
            embedded = svc.refresh_embeddings()
            if embedded:
                logger.info("Embedding refresh: %d items", embedded)
            return embedded
    except Exception as exc:
        logger.exception("embedding_refresh_task failed")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def cleanup_task(self):
    try:
        cutoff_30 = datetime.now(UTC) - timedelta(days=30)
        cutoff_7 = datetime.now(UTC) - timedelta(days=7)
        with db_session() as db:
            old_reminders = db.query(Reminder).filter(Reminder.sent == True, Reminder.created_at < cutoff_7).delete()
            old_notifications = (
                db.query(Notification)
                .filter(Notification.is_read == True, Notification.created_at < cutoff_30)
                .delete()
            )
            old_gossip = db.query(Gossip).filter(Gossip.is_featured == False, Gossip.scraped_at < cutoff_30).delete()
            logger.info(
                "Cleanup: %d reminders, %d notifications, %d gossip deleted",
                old_reminders,
                old_notifications,
                old_gossip,
            )
    except Exception as exc:
        logger.error("cleanup_task failed: %s", exc)
        raise self.retry(exc=exc)
