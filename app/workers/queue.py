import asyncio
from uuid import UUID

from app.workers.celery_app import INGEST_TASK_NAME, celery_app


class CeleryTaskQueue:
    async def enqueue_ingest(self, document_id: UUID) -> None:
        # The payload is the id only; the worker reloads the row and takes
        # tenant_id from it, never from the message.
        await asyncio.to_thread(
            celery_app.send_task, INGEST_TASK_NAME, args=[str(document_id)]
        )
