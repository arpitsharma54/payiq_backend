from __future__ import absolute_import, unicode_literals
import os
import logging
from celery import Celery
from celery.signals import worker_ready

logger = logging.getLogger(__name__)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'payiq.settings')

app = Celery('payiq')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@worker_ready.connect
def cleanup_stale_locks(sender, **kwargs):
    """
    Clean up stale bot locks when celery worker starts.
    This handles the case where the worker was killed/restarted while tasks were running.
    """
    try:
        from django.conf import settings
        import redis

        redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)

        # Find all bot locks
        lock_keys = redis_client.keys('celery_task_run_bot_lock_*')
        stop_flag_keys = redis_client.keys('bot_stop_flag_*')

        if lock_keys or stop_flag_keys:
            # Delete all stale locks and stop flags
            all_keys = lock_keys + stop_flag_keys
            if all_keys:
                deleted = redis_client.delete(*all_keys)
                logger.warning(f"Cleaned up {deleted} stale bot locks/flags on worker startup: {all_keys}")
        else:
            logger.info("No stale bot locks found on worker startup")

    except Exception as e:
        logger.error(f"Error cleaning up stale locks on worker startup: {e}")