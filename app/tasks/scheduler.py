"""
Background task scheduler using APScheduler
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

logger = logging.getLogger(__name__)

scheduler: AsyncIOScheduler = None


def start_scheduler():
    global scheduler

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        content_discovery_task,
        IntervalTrigger(hours=settings.discovery_interval_hours),
        id="content_discovery",
        name="Content Discovery Task",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )

    scheduler.add_job(
        gossip_scraping_task,
        IntervalTrigger(minutes=settings.gossip_scrape_interval_minutes),
        id="gossip_scraping",
        name="Gossip Scraping Task",
        replace_existing=True,
    )

    scheduler.add_job(
        reranking_task,
        IntervalTrigger(minutes=settings.reranking_interval_minutes),
        id="content_reranking",
        name="Content Re-ranking Task",
        replace_existing=True,
    )

    scheduler.add_job(
        content_enrichment_task,
        IntervalTrigger(minutes=settings.enrichment_interval_minutes),
        id="content_enrichment",
        name="Content Enrichment Task",
        replace_existing=True,
        next_run_time=datetime.now(UTC) + timedelta(minutes=2),
    )

    scheduler.add_job(
        reminder_task,
        IntervalTrigger(minutes=settings.reminder_check_interval_minutes),
        id="send_reminders",
        name="Send Reminders Task",
        replace_existing=True,
        next_run_time=datetime.now(UTC) + timedelta(seconds=30),
    )

    scheduler.add_job(
        cleanup_task,
        IntervalTrigger(hours=24),
        id="cleanup_old_data",
        name="Cleanup Old Data Task",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Background scheduler started")


def shutdown_scheduler():
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=True)
        logger.info("Background scheduler shutdown")


async def content_discovery_task():
    """Pull content from providers in batches.

    All provider HTTP calls are synchronous (httpx.Client), so we run the
    heavy lifting in a thread to avoid blocking the asyncio event loop (and
    therefore all web requests).
    """
    logger.info("Running content discovery task...")
    try:
        await asyncio.to_thread(_content_discovery_sync)
    except Exception as e:
        logger.error("Error in content discovery task: %s", e)


def _content_discovery_sync():
    """Synchronous worker executed in a thread pool."""
    from app.database import db_session
    from app.services.content_discovery import ContentDiscoveryService

    with db_session() as db:
        svc = ContentDiscoveryService(db)

        if svc.is_catalog_empty():
            logger.info("Catalog is empty — running initial seed...")
            total = svc.seed_catalog()
            logger.info("Initial seed completed: %d items added", total)
        else:
            result = svc.run_scheduled_sync()
            logger.info(
                "Content discovery completed: %d movies, %d TV shows",
                result["movies"],
                result["tv_shows"],
            )

        enriched = svc.enrich_sparse_content(batch_size=30)
        if enriched:
            logger.info("Detail enrichment completed: %d records", enriched)


async def content_enrichment_task():
    """Backfill episodes, runtime, language etc. on sparse content records.

    Runs on its own schedule so it doesn't depend on the 6-hour discovery cycle.
    """
    logger.info("Running content enrichment task...")
    try:
        await asyncio.to_thread(_content_enrichment_sync)
    except Exception as e:
        logger.error("Error in content enrichment task: %s", e)


def _content_enrichment_sync():
    from app.database import db_session
    from app.services.content_discovery import ContentDiscoveryService

    with db_session() as db:
        svc = ContentDiscoveryService(db)
        enriched = svc.enrich_sparse_content(batch_size=50)
        if enriched:
            logger.info("Enrichment pass completed: %d records", enriched)
        else:
            logger.info("No sparse content to enrich")


async def gossip_scraping_task():
    logger.info("Running gossip scraping task...")
    try:
        from app.database import db_session
        from app.repositories.library_repo import LibraryRepository
        from app.services.gossip_service import GossipService

        with db_session() as db:
            tracked = LibraryRepository(db).get_all_tracked_titles()
            svc = GossipService(db)
            results = await svc.scrape_latest(tracked[:20])
            logger.info(f"Gossip scraping completed: {len(results)} items")
    except Exception as e:
        logger.error(f"Error in gossip scraping task: {e}")


async def reranking_task():
    logger.info("Running content re-ranking task...")
    try:
        from app.database import db_session
        from app.models import User
        from app.services.ranking_service import RankingService

        with db_session() as db:
            users = db.query(User).all()
            for user in users:
                try:
                    svc = RankingService(db)
                    count = await svc.run_reranking(user.id)
                    logger.info(f"Re-ranking for {user.username}: {count} items")
                except Exception as e:
                    logger.error(f"Re-ranking error for {user.username}: {e}")
    except Exception as e:
        logger.error(f"Error in re-ranking task: {e}")


async def reminder_task():
    logger.info("Running reminder task...")
    try:
        from app.database import db_session
        from app.services.reminder_service import ReminderService

        with db_session() as db:
            svc = ReminderService(db)
            count = svc.process_due_reminders()
            logger.info(f"Processed {count} reminders")
    except Exception as e:
        logger.error(f"Error in reminder task: {e}")


async def cleanup_task():
    logger.info("Running cleanup task...")
    try:
        from app.database import db_session
        from app.models import Gossip, Notification, Reminder

        cutoff_30_days = datetime.now(UTC) - timedelta(days=30)
        cutoff_7_days = datetime.now(UTC) - timedelta(days=7)

        with db_session() as db:
            old_reminders = (
                db.query(Reminder)
                .filter(
                    Reminder.sent == True,
                    Reminder.created_at < cutoff_7_days,
                )
                .delete()
            )

            old_notifications = (
                db.query(Notification)
                .filter(
                    Notification.is_read == True,
                    Notification.created_at < cutoff_30_days,
                )
                .delete()
            )

            old_gossip = (
                db.query(Gossip)
                .filter(
                    Gossip.is_featured == False,
                    Gossip.scraped_at < cutoff_30_days,
                )
                .delete()
            )

            logger.info(
                "Cleanup: %d reminders, %d notifications, %d gossip items deleted",
                old_reminders,
                old_notifications,
                old_gossip,
            )
    except Exception as e:
        logger.error(f"Error in cleanup task: {e}")
