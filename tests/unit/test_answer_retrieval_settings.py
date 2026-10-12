"""retrieve_for_answer hands the deployment's retrieval settings to retrieve() (M10)."""

import uuid
from typing import Any

import pytest

from app.api import chat as chat_api
from app.core.config import Settings
from app.services.retrieval import RetrieveResult


@pytest.mark.asyncio
@pytest.mark.parametrize("weight", [1.0, 2.0])
async def test_the_rrf_dense_weight_setting_reaches_retrieval(
    monkeypatch: pytest.MonkeyPatch, weight: float
) -> None:
    seen: dict[str, Any] = {}

    async def fake_retrieve(**kwargs: Any) -> RetrieveResult:
        seen.update(kwargs)
        return RetrieveResult(items=[], trace=None)

    monkeypatch.setattr(chat_api, "retrieve", fake_retrieve)

    await chat_api.retrieve_for_answer(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        Settings(rrf_dense_weight=weight),
        tenant_id=uuid.uuid4(),
        query="q",
        document_ids=None,
        limit=6,
    )

    assert seen["dense_weight"] == weight
