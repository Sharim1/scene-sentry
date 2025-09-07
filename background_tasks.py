import logging
from app import app, scheduler, db
from models import User, Reminder
from ai_agents import RecommendationAgent
from datetime import datetime, timedelta

@scheduler.task('interval', id='continuous_discovery', minutes=30, misfire_grace_time=900)
def continuous_discovery_task():
    """Background task to continuously discover content for all users"""
    with app.app_context():
        try:
            users = User.query.all()
            agent = RecommendationAgent()
            
            for user in users:
                try:
                    logging.info(f"Running continuous discovery for user: {user.username}")
                    recommendations = agent.continuous_discovery(user)
                    logging.info(f"Generated {len(recommendations)} recommendations for {user.username}")
                    
                except Exception as e:
                    logging.error(f"Error in continuous discovery for user {user.username}: {e}")
                    
        except Exception as e:
            logging.error(f"Error in continuous discovery task: {e}")

@scheduler.task('interval', id='send_reminders', minutes=60, misfire_grace_time=900)
def send_reminders_task():
    """Send due reminders to users"""
    with app.app_context():
        try:
            # Get reminders that are due
            due_reminders = Reminder.query.filter(
                Reminder.scheduled_time <= datetime.utcnow(),
                Reminder.sent == False
            ).all()
            
            for reminder in due_reminders:
                try:
                    # In a real implementation, you would send actual notifications
                    # For now, just mark as sent and log
                    logging.info(f"Reminder sent to user {reminder.user_id}: {reminder.message}")
                    
                    reminder.sent = True
                    db.session.commit()
                    
                except Exception as e:
                    logging.error(f"Error sending reminder {reminder.id}: {e}")
                    
        except Exception as e:
            logging.error(f"Error in send reminders task: {e}")

@scheduler.task('interval', id='cleanup_old_data', hours=24, misfire_grace_time=3600)
def cleanup_old_data():
    """Clean up old data to keep database size manageable"""
    with app.app_context():
        try:
            # Clean up old dismissed recommendations (older than 30 days)
            from models import Recommendation, SearchLog
            
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            # Delete old dismissed recommendations
            old_recommendations = Recommendation.query.filter(
                Recommendation.dismissed == True,
                Recommendation.created_at < cutoff_date
            ).delete()
            
            # Delete old search logs (older than 7 days)
            search_cutoff = datetime.utcnow() - timedelta(days=7)
            old_searches = SearchLog.query.filter(
                SearchLog.created_at < search_cutoff
            ).delete()
            
            # Delete old sent reminders (older than 7 days)
            old_reminders = Reminder.query.filter(
                Reminder.sent == True,
                Reminder.created_at < search_cutoff
            ).delete()
            
            db.session.commit()
            
            logging.info(f"Cleanup completed: {old_recommendations} recommendations, "
                        f"{old_searches} search logs, {old_reminders} reminders deleted")
            
        except Exception as e:
            logging.error(f"Error in cleanup task: {e}")

def init_background_tasks():
    """Initialize background tasks"""
    try:
        if not scheduler.running:
            scheduler.start()
            logging.info("Background tasks scheduler started")
    except Exception as e:
        logging.error(f"Error starting scheduler: {e}")
