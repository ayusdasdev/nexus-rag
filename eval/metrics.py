"""Retrieval metrics (guide 8.3). Pure functions over chunk texts and gold spans.

A retrieved chunk is relevant when it contains a gold span after case and whitespace
normalisation. Labels are spans, not chunk ids, so they survive re-chunking.
"""

import math
import re
from collections.abc import Sequence
from typing import Literal

Mode = Literal["any", "all"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def is_hit(chunk_text: str, gold_spans: Sequence[str]) -> bool:
    text = _norm(chunk_text)
    return any(_norm(span) in text for span in gold_spans)


def first_hit_rank(retrieved: Sequence[str], gold_spans: Sequence[str]) -> int | None:
    """1-based rank of the first relevant chunk, or None."""
    for rank, text in enumerate(retrieved, start=1):
        if is_hit(text, gold_spans):
            return rank
    return None


def recall_at_k(
    retrieved: Sequence[str], gold_spans: Sequence[str], k: int, mode: Mode = "any"
) -> float:
    """mode "any": 1.0 if any top-k chunk has any span (hit rate).
    mode "all" (multi-chunk questions): the share of spans found in the top k."""
    top = retrieved[:k]
    if mode == "any":
        return 1.0 if any(is_hit(text, gold_spans) for text in top) else 0.0
    found = sum(1 for span in gold_spans if any(is_hit(text, [span]) for text in top))
    return found / len(gold_spans) if gold_spans else 0.0


def precision_at_k(
    retrieved: Sequence[str], gold_spans: Sequence[str], k: int
) -> float:
    """Relevant chunks in the top k, divided by k (even if fewer than k were returned)."""
    return sum(1 for text in retrieved[:k] if is_hit(text, gold_spans)) / k


def ndcg_at_k(retrieved: Sequence[str], gold_spans: Sequence[str], k: int) -> float:
    """Binary-relevance nDCG@k. The ideal ordering puts the same retrieved relevant items
    first, so this scores the ordering of what was retrieved; recall scores coverage."""
    rels = [1 if is_hit(text, gold_spans) else 0 for text in retrieved[:k]]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))
    ideal = sum(
        rel / math.log2(i + 2) for i, rel in enumerate(sorted(rels, reverse=True))
    )
    return dcg / ideal if ideal else 0.0


def mrr(first_ranks: Sequence[int | None]) -> float:
    if not first_ranks:
        return 0.0
    return sum(1 / r for r in first_ranks if r) / len(first_ranks)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
