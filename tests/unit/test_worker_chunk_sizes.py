"""The worker chunks with the configured sizes; with no setting, 350 and 50 (M8 E4)."""

import pytest

from app.core.config import Settings
from app.workers import tasks


def test_with_no_setting_the_worker_chunks_at_350_with_50_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "get_settings", lambda: Settings(_env_file=None))

    assert tasks._chunk_sizes() == {"max_tokens": 350, "overlap": 50}


def test_the_worker_chunks_at_the_configured_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(chunk_max_tokens=200, chunk_overlap_tokens=50)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    assert tasks._chunk_sizes() == {"max_tokens": 200, "overlap": 50}
