from collections.abc import Hashable, Iterable, Sequence

RRF_K = 60


def rrf[T: Hashable](
    ranked_lists: Sequence[Sequence[T]], k: int = RRF_K
) -> list[tuple[T, float]]:
    """Reciprocal Rank Fusion: score(id) = sum over lists containing id of 1/(k + rank).

    Ranks are 1-based positions in each list; scores are ignored, which is the point:
    dense, BM25 and reranker scores live on incomparable scales. An id repeated inside
    one list counts once, at its best rank. Ties are broken by str(id) ascending so the
    output is deterministic regardless of input order.
    """
    return rrf_from_ranks(
        [
            list(zip(ranked, range(1, len(ranked) + 1), strict=True))
            for ranked in ranked_lists
        ],
        k,
    )


def rrf_from_ranks[T: Hashable](
    ranked_lists: Sequence[Iterable[tuple[T, int]]], k: int = RRF_K
) -> list[tuple[T, float]]:
    """rrf() over explicit (id, rank) pairs, for callers whose lists already carry ranks."""
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k}")
    scores: dict[T, float] = {}
    for ranked in ranked_lists:
        best: dict[T, int] = {}
        for item, rank in ranked:
            if rank < 1:
                raise ValueError(f"rank must be >= 1, got {rank}")
            best[item] = min(rank, best.get(item, rank))
        for item, rank in best.items():
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))
