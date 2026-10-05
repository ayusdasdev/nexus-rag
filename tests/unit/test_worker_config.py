from app.core.errors import TransientError
from app.workers import tasks  # noqa: F401 - registers process_document
from app.workers.celery_app import PROCESS_DOCUMENT_TASK, celery_app


def test_process_document_is_registered_under_its_name() -> None:
    assert PROCESS_DOCUMENT_TASK == "process_document"
    assert PROCESS_DOCUMENT_TASK in celery_app.tasks


def test_process_document_retry_and_ack_policy() -> None:
    task = celery_app.tasks[PROCESS_DOCUMENT_TASK]

    assert task.acks_late is True
    assert task.max_retries == 3
    assert task.retry_backoff is True
    assert task.autoretry_for == (TransientError,)
    assert task.soft_time_limit == 900
    assert task.time_limit == 1200
