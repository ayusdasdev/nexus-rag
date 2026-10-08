import pytest

from app.providers.reranker import (
    RERANK_MAX_CANDIDATES,
    CrossEncoderReranker,
    is_cached,
    rerank,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_cached(), reason="reranker not cached; run make fetch-models"
    ),
]


def test_cross_encoder_scores_the_relevant_passage_higher() -> None:
    scores = CrossEncoderReranker().score(
        "How long does the Nexus Widget battery last?",
        [
            "The Nexus Widget battery lasts eight hours under normal use.",
            "Parking passes must be renewed every January at the front desk.",
        ],
    )

    assert scores[0] > scores[1]


def test_rerank_wrapper_works_with_the_real_cross_encoder() -> None:
    result = rerank(
        CrossEncoderReranker(),
        "battery life",
        ["battery life lasts eight hours", "unrelated parking notice"],
    )

    assert len(result.scores) == 2
    assert result.candidates_scored == 2
    assert result.truncated is False
    assert result.scores[0] > result.scores[1]


def test_rerank_max_candidates_is_enforced_with_the_real_model() -> None:
    texts = [f"filler passage number {i}" for i in range(RERANK_MAX_CANDIDATES + 3)]

    result = rerank(CrossEncoderReranker(), "filler", texts)

    assert result.truncated is True
    assert result.candidates_scored == RERANK_MAX_CANDIDATES
    assert len(result.scores) == RERANK_MAX_CANDIDATES
