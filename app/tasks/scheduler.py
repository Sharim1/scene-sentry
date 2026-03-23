"""
Background task scheduler using APScheduler
"""
import logging
from datetime import datetime, timedelta, timezone
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
        IntervalTrigger(hours=6),
        id="content_discovery",
        name="Content Discovery Task",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
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
        reminder_task,
        IntervalTrigger(minutes=60),
        id="send_reminders",
        name="Send Reminders Task",
        replace_existing=True,
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
    """Pull content from providers. Seeds the catalog on first run, then
    fetches the next page on each subsequent run so the catalog keeps growing."""
    logger.info("Running content discovery task...")
    try:
        from app.database import db_session
        from app.services.content_discovery import ContentDiscoveryService

        with db_session() as db:
            svc = ContentDiscoveryService(db)

            if svc.is_catalog_empty():
                logger.info("Catalog is empty — running initial seed...")
                total = await svc.seed_catalog()
                logger.info(f"Initial seed completed: {total} items added")
            else:
                movies = await svc.discover_and_save_movies(limit=100)
                shows = await svc.discover_and_save_tv_shows(limit=100)
                logger.info(
                    f"Content discovery completed: {movies} movies, {shows} TV shows (next pages)"
                )
    except Exception as e:
        logger.error(f"Error in content discovery task: {e}")


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
        from app.models import Reminder, Gossip
        from app.models.ranking import UserContentRank

        cutoff_30_days = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_7_days = datetime.now(timezone.utc) - timedelta(days=7)

        with db_session() as db:
            old_reminders = db.query(Reminder).filter(
                Reminder.sent == True,
                Reminder.created_at < cutoff_7_days,
            ).delete()

            old_gossip = db.query(Gossip).filter(
                Gossip.is_featured == False,
                Gossip.scraped_at < cutoff_30_days,
            ).delete()

            logger.info(f"Cleanup: {old_reminders} reminders, {old_gossip} gossip items deleted")
    except Exception as e:
        logger.error(f"Error in cleanup task: {e}")
