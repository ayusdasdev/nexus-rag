"""Reciprocal Rank Fusion as a pure function: score(id) = sum over lists of 1/(k + rank).

Expected values are worked out by hand in the comments; ranks are 1-based.
"""

import uuid

import pytest

from app.services.fusion import rrf, rrf_from_ranks


def test_guide_example_doc_liked_by_both_lists_beats_a_one_list_favourite() -> None:
    # dense:  A=1, B=2, C=3, D=4      sparse: E=1, B=2, F=3, A=4
    # A: 1/(60+1) + 1/(60+4) = 0.016393 + 0.015625 = 0.032018
    # B: 1/(60+2) + 1/(60+2) = 2 * 0.016129       = 0.032258   -> B > A
    fused = dict(rrf([["A", "B", "C", "D"], ["E", "B", "F", "A"]]))

    assert fused["A"] == pytest.approx(1 / 61 + 1 / 64)
    assert fused["B"] == pytest.approx(2 / 62)
    assert fused["B"] > fused["A"]


def test_result_is_sorted_by_fused_score_descending() -> None:
    # B 0.032258 > A 0.032018 > E 1/61=0.016393 > C 1/63=0.015873 > F 1/63 > D 1/64
    # C and F tie at 1/63; the tie is broken by id, so C before F.
    fused = rrf([["A", "B", "C", "D"], ["E", "B", "F", "A"]])

    assert [item for item, _ in fused] == ["B", "A", "E", "C", "F", "D"]


def test_a_doc_in_only_one_list_scores_its_single_reciprocal_rank() -> None:
    # X is rank 3 in the second list only: 1/(60+3) = 0.015873
    fused = dict(rrf([["A"], ["B", "C", "X"]]))

    assert fused["X"] == pytest.approx(1 / 63)


def test_ties_are_broken_by_id_ascending_whatever_the_input_order() -> None:
    # Each of z, a, m is rank 1 in exactly one list: all score 1/61.
    assert [item for item, _ in rrf([["z"], ["a"], ["m"]])] == ["a", "m", "z"]
    assert [item for item, _ in rrf([["m"], ["z"], ["a"]])] == ["a", "m", "z"]


def test_uuid_ties_are_broken_by_their_string_form() -> None:
    low = uuid.UUID("00000000-0000-0000-0000-000000000001")
    high = uuid.UUID("ffffffff-0000-0000-0000-000000000000")

    assert [item for item, _ in rrf([[high], [low]])] == [low, high]


def test_no_lists_and_empty_lists_fuse_to_nothing() -> None:
    assert rrf([]) == []
    assert rrf([[], []]) == []


def test_an_empty_list_contributes_nothing() -> None:
    # A: 1/61 from the only non-empty list.
    [(item, score)] = rrf([["A"], []])

    assert item == "A"
    assert score == pytest.approx(1 / 61)


def test_a_duplicate_inside_one_list_counts_once_at_its_best_rank() -> None:
    # ["A", "B", "A"]: A counts at rank 1 only -> 1/61, not 1/61 + 1/63.
    # B is rank 2 -> 1/62.
    fused = dict(rrf([["A", "B", "A"]]))

    assert fused["A"] == pytest.approx(1 / 61)
    assert fused["B"] == pytest.approx(1 / 62)


def test_k_changes_how_steeply_rank_is_discounted() -> None:
    # k=0: A rank 1 -> 1/1 = 1.0, B rank 2 -> 1/2 = 0.5
    fused = rrf([["A", "B"]], k=0)

    assert [item for item, _ in fused] == ["A", "B"]
    assert [score for _, score in fused] == pytest.approx([1.0, 0.5])


def test_negative_k_is_rejected() -> None:
    # k=-1 would make rank 1 divide by zero.
    with pytest.raises(ValueError, match="k"):
        rrf([["A"]], k=-1)


def test_same_input_gives_the_same_output() -> None:
    lists = [["c", "a", "b"], ["b", "c"], ["a"]]

    assert rrf(lists) == rrf(lists)


# --- rrf_from_ranks: the same formula over explicit (id, rank) pairs ---------------


def test_rrf_from_ranks_uses_the_given_rank_not_the_position() -> None:
    # X sits first in its list but carries rank 3: 1/(60+3) = 0.015873
    [(item, score)] = rrf_from_ranks([[("X", 3)]])

    assert item == "X"
    assert score == pytest.approx(1 / 63)


def test_rrf_from_ranks_counts_a_duplicate_once_at_its_best_rank() -> None:
    # A appears at ranks 4 and 2 in one list: only rank 2 counts -> 1/62
    [(item, score)] = rrf_from_ranks([[("A", 4), ("A", 2)]])

    assert item == "A"
    assert score == pytest.approx(1 / 62)


def test_rrf_from_ranks_rejects_a_rank_below_1() -> None:
    with pytest.raises(ValueError, match="rank"):
        rrf_from_ranks([[("A", 0)]])


# --- weighted RRF (M10): score(id) = sum of weight_list / (k + rank) ------------------


def test_weights_of_one_are_exactly_plain_rrf() -> None:
    lists = [[("a", 1), ("b", 2), ("c", 3)], [("c", 1), ("d", 2)]]

    assert rrf_from_ranks(lists, weights=[1.0, 1.0]) == rrf_from_ranks(lists)


def test_a_weighted_list_lifts_its_own_items_by_hand() -> None:
    # k = 60. dense-only "d" at rank 1: 2.0/61 = 0.032787; sparse-only "s" at rank 1:
    # 1.0/61 = 0.016393. Unweighted they tie and "d" < "s" only by id.
    lists = [[("x", 1)], [("y", 1)]]

    weighted = rrf_from_ranks(lists, weights=[2.0, 1.0])

    assert [item for item, _ in weighted] == ["x", "y"]
    assert [score for _, score in weighted] == pytest.approx([2.0 / 61, 1.0 / 61])


def test_a_dense_only_rank_1_hit_rises_from_last_to_31st_at_weight_2() -> None:
    # q044's pattern: gold at dense rank 1, missing from BM25; 39 items both lists found,
    # both_i at dense rank i+1 and sparse rank i (k = 60).
    # Plain: gold 1/61 = 0.01639, below every both_i (lowest 1/100 + 1/99 = 0.0201): last.
    # Weight 2: gold 2/61 = 0.03279; both_30 = 2/91 + 1/90 = 0.03309 (above),
    # both_31 = 2/92 + 1/91 = 0.03273 (below), so gold is 31st.
    dense = [("gold", 1)] + [(f"both{i}", i + 1) for i in range(1, 40)]
    sparse = [(f"both{i}", i) for i in range(1, 40)]

    plain = [item for item, _ in rrf_from_ranks([dense, sparse])]
    weighted = [item for item, _ in rrf_from_ranks([dense, sparse], weights=[2.0, 1.0])]

    assert plain.index("gold") == 39
    assert weighted.index("gold") == 30


@pytest.mark.parametrize("weights", [[1.0], [1.0, 1.0, 1.0], [0.0, 1.0], [-1.0, 1.0]])
def test_weights_must_match_the_lists_and_be_positive(weights: list[float]) -> None:
    with pytest.raises(ValueError):
        rrf_from_ranks([[("a", 1)], [("b", 1)]], weights=weights)
