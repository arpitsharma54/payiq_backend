from celery import shared_task
from django.conf import settings
import redis
import logging

logger = logging.getLogger(__name__)

# Connect to Redis (using same connection as Celery)
redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)

@shared_task(name='deposit.task.run_bot')
def run_bot():
    """
    Run bot task with lock to prevent concurrent execution.
    If a previous task is still running, this task will skip execution.
    """
    # Lock key for this task
    lock_key = 'celery_task_run_bot_lock'
    lock_timeout = 3600  # Lock expires after 1 hour (safety measure)
    
    # Try to acquire lock using Redis SET with NX (only set if not exists)
    # This is atomic and prevents race conditions
    lock_acquired = redis_client.set(lock_key, 'locked', nx=True, ex=lock_timeout)
    
    if not lock_acquired:
        # Another task is already running
        logger.info("Task 'run_bot' is already running. Skipping execution.")
        return "Task skipped: Previous task is still running"
    
    try:
        # Lock acquired, execute the bot
        logger.info("Starting bot task execution...")
        from core.bot.bot import run_bot as execute_bot
        execute_bot()
        logger.info("Bot task execution completed.")
        return "Task completed successfully"
    except Exception as e:
        logger.error(f"Bot task execution failed: {str(e)}", exc_info=True)
        raise
    finally:
        # Always release the lock when done
        redis_client.delete(lock_key)
        logger.info("Lock released.")