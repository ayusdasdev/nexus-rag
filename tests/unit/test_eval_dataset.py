"""The locked v1 eval set and its hold-out split (M8)."""

import json
from collections import Counter

from eval.dataset import DATASETS, load_questions, make_split

SPLIT = json.loads((DATASETS / "v1.split.json").read_text())


def test_v1_has_the_approved_60_questions_with_unique_ids() -> None:
    questions = load_questions()

    assert len(questions) == 60
    assert len({q["id"] for q in questions}) == 60
    assert Counter(q["type"] for q in questions) == {
        "factoid": 21,
        "paraphrase": 12,
        "exact-token": 9,
        "multi-chunk": 9,
        "unanswerable": 9,
    }


def test_unanswerables_have_no_gold_and_answerables_do() -> None:
    for q in load_questions():
        if q["type"] == "unanswerable":
            assert q["gold"] == [] and q["answerable"] is False, q["id"]
        else:
            assert q["gold"] and q["answerable"] is True, q["id"]


def test_every_id_is_in_exactly_one_split() -> None:
    ids = {q["id"] for q in load_questions()}
    dev, holdout = set(SPLIT["dev"]), set(SPLIT["holdout"])

    assert dev | holdout == ids
    assert not dev & holdout


def test_the_split_is_reproducible_from_its_recorded_seed() -> None:
    again = make_split(load_questions(), seed=SPLIT["seed"], fraction=SPLIT["fraction"])

    assert again == {"dev": SPLIT["dev"], "holdout": SPLIT["holdout"]}


def test_every_type_is_in_both_splits_at_about_20_percent() -> None:
    types = {q["id"]: q["type"] for q in load_questions()}
    held = Counter(types[i] for i in SPLIT["holdout"])
    dev = Counter(types[i] for i in SPLIT["dev"])

    assert held == {
        "factoid": 4,
        "paraphrase": 2,
        "exact-token": 2,
        "multi-chunk": 2,
        "unanswerable": 2,
    }
    assert all(dev[t] > 0 for t in held)
    assert len(SPLIT["holdout"]) == 12
