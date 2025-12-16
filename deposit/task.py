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
        from core.bot.iob_bot.iob_bot import run_bot as execute_bot
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


@shared_task(name='deposit.task.run_single_bot', bind=True)
def run_single_bot(self, bank_account_id):
    """
    Run bot for a specific bank account.
    The bot runs continuously with its own internal loop (browser stays open).
    Stops when user sets the stop flag.
    """
    lock_key = f'celery_task_run_bot_lock_{bank_account_id}'
    stop_flag_key = f'bot_stop_flag_{bank_account_id}'
    lock_timeout = 86400  # Lock expires after 24 hours (safety measure)

    # Try to acquire lock atomically
    lock_acquired = redis_client.set(lock_key, self.request.id, nx=True, ex=lock_timeout)

    if not lock_acquired:
        logger.info(f"Bot for bank account {bank_account_id} is already running.")
        return f"Bot for account {bank_account_id} already running"

    # Clear any existing stop flag
    redis_client.delete(stop_flag_key)

    try:
        logger.info(f"Starting bot for account {bank_account_id}...")

        # Import inside function to avoid circular imports
        from core.bot.registry import run_bot_for_account, run_async
        from core.bot.iob_bot.iob_bot import BotStoppedException

        try:
            # Run the bot (it has its own internal loop with browser staying open)
            run_async(run_bot_for_account, bank_account_id)
            logger.info(f"Bot completed for account {bank_account_id}.")
            return f"Bot for account {bank_account_id} completed"

        except BotStoppedException:
            logger.info(f"Bot stopped by user for account {bank_account_id}")
            return f"Bot for account {bank_account_id} stopped by user"

        except Exception as e:
            logger.error(f"Bot failed for account {bank_account_id}: {str(e)}", exc_info=True)
            # Send error status via WebSocket
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                from merchants.models import BankAccount
                bank_account = BankAccount.objects.get(id=bank_account_id)
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "task_status_updates",
                    {
                        "type": "task_update",
                        "status": "error",
                        "message": f"Bot failed: {str(e)}",
                        "bank_account_id": bank_account_id,
                        "merchant_id": bank_account.merchant_id,
                    }
                )
            except Exception as ws_error:
                logger.warning(f"Could not send WebSocket error update: {str(ws_error)}")
            raise

    finally:
        # Always release the lock and clean up stop flag when done
        redis_client.delete(lock_key)
        redis_client.delete(stop_flag_key)
        logger.info(f"Lock and stop flag released for bank account {bank_account_id}.")
