"""Retrieval metrics as pure functions, checked against hand-computed values (guide 8.3)."""

import math

import pytest

from eval.metrics import (
    first_hit_rank,
    is_hit,
    mean,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

A = "Readings are kept for ninety days at full resolution."
B = "Alert events are kept for one year."
C = "The hub connects outward over HTTPS on port 443."
GOLD = ["kept for ninety days"]


def test_is_hit_normalises_case_and_whitespace() -> None:
    assert is_hit("Readings are KEPT for\n\n  ninety   days.", GOLD)
    assert not is_hit(B, GOLD)


def test_is_hit_accepts_any_of_several_gold_spans() -> None:
    assert is_hit(C, ["kept for ninety days", "port 443"])


def test_first_hit_rank_is_one_based_or_none() -> None:
    assert first_hit_rank([B, C, A], GOLD) == 3
    assert first_hit_rank([B, C], GOLD) is None


def test_mrr_matches_the_guides_three_question_example() -> None:
    # First correct chunk at rank 1, at rank 3, and not at all: (1 + 1/3 + 0) / 3 = 0.444...
    assert mrr([1, 3, None]) == pytest.approx(4 / 9)


def test_all_miss_and_all_hit_at_rank_one() -> None:
    assert mrr([None, None]) == 0.0
    assert mrr([1, 1, 1]) == 1.0
    assert recall_at_k([B, C], GOLD, 5) == 0.0
    assert recall_at_k([A, B], GOLD, 1) == 1.0


def test_recall_at_k_cuts_the_list_at_k() -> None:
    # The hit is at rank 3: outside top 2, inside top 3.
    assert recall_at_k([B, C, A], GOLD, 2) == 0.0
    assert recall_at_k([B, C, A], GOLD, 3) == 1.0


def test_recall_for_multi_chunk_questions_is_the_share_of_spans_covered() -> None:
    # mode "all": span 1 at rank 1, span 2 at rank 4. Top 3 covers 1 of 2 = 0.5; top 5 both.
    spans = ["kept for ninety days", "port 443"]
    retrieved = [A, B, B, C]
    assert recall_at_k(retrieved, spans, 3, mode="all") == 0.5
    assert recall_at_k(retrieved, spans, 5, mode="all") == 1.0


def test_precision_divides_by_k_even_when_the_list_is_shorter() -> None:
    # 1 relevant in a 2-item list, k = 10: 1/10.
    assert precision_at_k([A, B], GOLD, 10) == pytest.approx(0.1)
    # Duplicate relevant chunks both count: 2 of top 3.
    assert precision_at_k([A, A, B], GOLD, 3) == pytest.approx(2 / 3)


def test_ndcg_by_hand() -> None:
    # rel = [0, 1, 0]; DCG = 1/log2(2+1) = 0.6309; ideal [1, 0, 0]: IDCG = 1/log2(2) = 1.
    assert ndcg_at_k([B, A, C], GOLD, 3) == pytest.approx(1 / math.log2(3))
    # Perfect ordering, and duplicates both relevant at the top: 1.0.
    assert ndcg_at_k([A, A, B], GOLD, 3) == pytest.approx(1.0)
    # No relevant item at all: 0.
    assert ndcg_at_k([B, C], GOLD, 3) == 0.0


def test_ndcg_ignores_items_beyond_k() -> None:
    # The only hit is at rank 4, outside k = 3.
    assert ndcg_at_k([B, C, B, A], GOLD, 3) == 0.0


def test_mean_of_nothing_is_none_not_zero() -> None:
    assert mean([]) is None
    assert mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)
