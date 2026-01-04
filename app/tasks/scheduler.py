"""
Background task scheduler using APScheduler
"""
import logging
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: AsyncIOScheduler = None


def start_scheduler():
    """Start the background task scheduler"""
    global scheduler
    
    scheduler = AsyncIOScheduler()
    
    # Add scheduled jobs
    scheduler.add_job(
        gossip_scraping_task,
        IntervalTrigger(minutes=settings.gossip_scrape_interval_minutes),
        id="gossip_scraping",
        name="Gossip Scraping Task",
        replace_existing=True
    )
    
    scheduler.add_job(
        discovery_task,
        IntervalTrigger(minutes=settings.discovery_interval_minutes),
        id="continuous_discovery",
        name="Continuous Discovery Task",
        replace_existing=True
    )
    
    scheduler.add_job(
        reminder_task,
        IntervalTrigger(minutes=60),
        id="send_reminders",
        name="Send Reminders Task",
        replace_existing=True
    )
    
    scheduler.add_job(
        cleanup_task,
        IntervalTrigger(hours=24),
        id="cleanup_old_data",
        name="Cleanup Old Data Task",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Background scheduler started")


def shutdown_scheduler():
    """Shutdown the scheduler gracefully"""
    global scheduler
    
    if scheduler:
        scheduler.shutdown(wait=True)
        logger.info("Background scheduler shutdown")


async def gossip_scraping_task():
    """Background task to scrape entertainment gossip"""
    logger.info("Running gossip scraping task...")
    
    try:
        from app.agents.gossip_agent import gossip_agent
        from app.database import db_session
        from app.models import User, LibraryItem
        from app.models.library import WatchStatus
        
        # Get all unique tracked titles from all users
        tracked_titles = set()
        
        with db_session() as db:
            items = db.query(LibraryItem).filter(
                LibraryItem.status.in_([WatchStatus.WATCHING, WatchStatus.PLANNED])
            ).all()
            
            for item in items:
                if item.content:
                    tracked_titles.add(item.content.title)
        
        # Run gossip scraper
        results = await gossip_agent.scrape_gossip(list(tracked_titles)[:20])
        
        logger.info(f"Gossip scraping completed: {len(results)} items")
        
    except Exception as e:
        logger.error(f"Error in gossip scraping task: {e}")


async def discovery_task():
    """Background task to run discovery for all users"""
    logger.info("Running discovery task...")
    
    try:
        from app.agents.graph import discovery_graph
        from app.database import db_session
        from app.models import User
        
        with db_session() as db:
            users = db.query(User).all()
            
            for user in users:
                try:
                    logger.info(f"Running discovery for user: {user.username}")
                    results = await discovery_graph.run_discovery(user.id)
                    logger.info(f"Discovery for {user.username}: {len(results)} recommendations")
                    
                except Exception as e:
                    logger.error(f"Error in discovery for user {user.username}: {e}")
                    continue
                    
    except Exception as e:
        logger.error(f"Error in discovery task: {e}")


async def reminder_task():
    """Send due reminders to users"""
    logger.info("Running reminder task...")
    
    try:
        from app.database import db_session
        from app.models import Reminder
        
        with db_session() as db:
            # Get reminders that are due
            due_reminders = db.query(Reminder).filter(
                Reminder.scheduled_time <= datetime.utcnow(),
                Reminder.sent == False
            ).all()
            
            for reminder in due_reminders:
                try:
                    # In a real implementation, send actual notifications
                    # For now, just mark as sent and log
                    logger.info(f"Reminder due for user {reminder.user_id}: {reminder.message}")
                    
                    reminder.sent = True
                    reminder.sent_at = datetime.utcnow()
                    
                except Exception as e:
                    logger.error(f"Error sending reminder {reminder.id}: {e}")
            
            db.commit()
            logger.info(f"Processed {len(due_reminders)} reminders")
            
    except Exception as e:
        logger.error(f"Error in reminder task: {e}")


async def cleanup_task():
    """Clean up old data to keep database manageable"""
    logger.info("Running cleanup task...")
    
    try:
        from app.database import db_session
        from app.models import Recommendation, SearchLog, Reminder, Gossip
        
        cutoff_30_days = datetime.utcnow() - timedelta(days=30)
        cutoff_7_days = datetime.utcnow() - timedelta(days=7)
        
        with db_session() as db:
            # Delete old dismissed recommendations (older than 30 days)
            old_recs = db.query(Recommendation).filter(
                Recommendation.dismissed == True,
                Recommendation.created_at < cutoff_30_days
            ).delete()
            
            # Delete old search logs (older than 7 days)
            old_searches = db.query(SearchLog).filter(
                SearchLog.created_at < cutoff_7_days
            ).delete()
            
            # Delete old sent reminders (older than 7 days)
            old_reminders = db.query(Reminder).filter(
                Reminder.sent == True,
                Reminder.created_at < cutoff_7_days
            ).delete()
            
            # Delete old gossip (older than 30 days, not featured)
            old_gossip = db.query(Gossip).filter(
                Gossip.is_featured == False,
                Gossip.scraped_at < cutoff_30_days
            ).delete()
            
            logger.info(f"Cleanup completed: {old_recs} recommendations, "
                        f"{old_searches} search logs, {old_reminders} reminders, "
                        f"{old_gossip} gossip items deleted")
            
    except Exception as e:
        logger.error(f"Error in cleanup task: {e}")

