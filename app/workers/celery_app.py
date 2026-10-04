from celery import Celery

from app.core.config import get_settings

INGEST_TASK_NAME = "ingest_document"

_settings = get_settings()

celery_app = Celery(
    "nexus",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Must exceed the longest allowed task time, or Redis redelivers a task
    # that is still running. Default is 3600s.
    broker_transport_options={"visibility_timeout": 7200},
)
