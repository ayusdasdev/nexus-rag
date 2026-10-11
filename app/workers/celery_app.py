from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging

PROCESS_DOCUMENT_TASK = "process_document"

_settings = get_settings()

celery_app = Celery(
    "nexus",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_reject_on_worker_lost=True,
    # One task at a time per process: a parse can take minutes.
    worker_prefetch_multiplier=1,
    # Must exceed the longest allowed task time, or Redis redelivers a task
    # that is still running. Default is 3600s.
    broker_transport_options={"visibility_timeout": 7200},
)


@setup_logging.connect  # type: ignore[untyped-decorator]
def use_json_logs(**_: Any) -> None:
    """The worker logs the same JSON lines as the API (M9 9.1). Connecting this receiver
    also stops Celery from installing its own handlers."""
    configure_logging(_settings.log_level)
