import logging

from celery import Celery
from kombu import Queue

from app.core.config import Settings

settings = Settings()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
celery_app = Celery("fuma", broker=settings.redis_dsn.get_secret_value())
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_default_queue="general",
    task_create_missing_queues=False,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={},
    imports=("app.workers.tasks",),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# The database scheduler recovers work independently of Redis message retention.
celery_app.conf.task_queues = (
    Queue("general", routing_key="general"),
    Queue("files", routing_key="files"),
)
