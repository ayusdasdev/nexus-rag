import asyncio
from uuid import UUID

from app.workers.celery_app import PROCESS_DOCUMENT_TASK, celery_app


class CeleryTaskQueue:
    async def enqueue_ingest(self, document_id: UUID) -> None:
        # The payload is the id only; the worker reloads the row and takes
        # tenant_id from it, never from the message.
        await asyncio.to_thread(
            celery_app.send_task, PROCESS_DOCUMENT_TASK, args=[str(document_id)]
        )
