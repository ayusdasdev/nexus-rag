"""The locked eval set (v1) and its reproducible, type-stratified hold-out split (M8)."""

import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "eval" / "datasets"
CORPUS = ROOT / "eval" / "corpus"


def load_questions(name: str = "v1") -> list[dict[str, Any]]:
    path = DATASETS / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def make_split(
    questions: Sequence[dict[str, Any]], seed: int, fraction: float = 0.2
) -> dict[str, list[str]]:
    """Hold out round(fraction * n) of each type (at least 1, never all), chosen by a
    seeded RNG over ids sorted within each type, so every type is in both splits."""
    rng = random.Random(seed)
    holdout: set[str] = set()
    for kind in sorted({q["type"] for q in questions}):
        ids = sorted(q["id"] for q in questions if q["type"] == kind)
        n = min(len(ids) - 1, max(1, round(fraction * len(ids))))
        holdout.update(rng.sample(ids, n))
    ordered = sorted(q["id"] for q in questions)
    return {
        "dev": [i for i in ordered if i not in holdout],
        "holdout": [i for i in ordered if i in holdout],
    }
