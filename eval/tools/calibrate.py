"""Calibrate the LLM judge against your own grades (M8, guide 8.4).

    uv run python -m eval.tools.calibrate --run E3-gen

Shows 15 answers of a generation run, one at a time: question, reference, sources and
answer. The 15 are drawn (seeded) from the fixed 20-question judge sample, so you can grade
before the judge has run. You grade correctness (0/1/2) and faithfulness (y/n). Each grade
is saved to eval/calibration/<run>.grades.jsonl as soon as you give it; q quits and a re-run
resumes. You see no checks or verdicts. Once the judge has run, a re-run prints how often
it agrees with you. Your grades are the ground truth; the judge never reads them.
"""

import argparse
import json
import random
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

CALIBRATION_SIZE = 15
ROOT = Path(__file__).resolve().parents[2]

Grade = tuple[int | None, bool | None]


def calibration_ids(
    sample: Sequence[str], seed: int, size: int = CALIBRATION_SIZE
) -> list[str]:
    return sorted(random.Random(seed).sample(sorted(sample), size))


def _show_item(item: Mapping[str, Any]) -> str:
    sources = "\n".join(f"  [{n}] {text}" for n, text in enumerate(item["sources"], 1))
    return (
        f"\n=== {item['id']} ===\nQUESTION: {item['question']}\n"
        f"REFERENCE: {item['reference_answer'] or '(unanswerable: should refuse)'}\n"
        f"SOURCES:\n{sources or '  (none)'}\nANSWER: {item['answer']}\n"
    )


def grade(
    items: Sequence[Mapping[str, Any]],
    out: Path,
    ask: Callable[[str], str] = input,
    show: Callable[[str], None] = print,
) -> None:
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.read_text().splitlines()}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as f:
        for item in items:
            if item["id"] in done:
                continue
            show(_show_item(item))
            correctness = None
            while correctness is None:
                raw = ask("correctness 0/1/2 (q quits): ").strip().lower()
                if raw == "q":
                    return
                correctness = int(raw) if raw in ("0", "1", "2") else None
            faithful = None
            while faithful is None:
                raw = ask("faithful to the sources? y/n (q quits): ").strip().lower()
                if raw == "q":
                    return
                faithful = {"y": True, "n": False}.get(raw)
            f.write(
                json.dumps(
                    {"id": item["id"], "correctness": correctness, "faithful": faithful}
                )
                + "\n"
            )
            f.flush()


def agreement(human: Mapping[str, Grade], judge: Mapping[str, Grade]) -> dict[str, Any]:
    """Agreement on the ids both graded; judge errors (None) are counted, not compared."""
    both = [i for i in human if i in judge]
    errors = [i for i in both if judge[i][0] is None]
    scored = [i for i in both if judge[i][0] is not None]

    def rate(agree: int, n: int) -> dict[str, Any]:
        return {"agree": agree, "n": n, "rate": agree / n if n else None}

    exact = sum(1 for i in scored if human[i][0] == judge[i][0])
    within = sum(1 for i in scored if abs((human[i][0] or 0) - (judge[i][0] or 0)) <= 1)
    faith = [i for i in scored if judge[i][1] is not None]
    return {
        "n": len(scored),
        "judge_errors": len(errors),
        "correctness_exact": rate(exact, len(scored)),
        "correctness_within_1": rate(within, len(scored)),
        "faithful": rate(
            sum(1 for i in faith if human[i][1] == judge[i][1]), len(faith)
        ),
        "confusion": dict(Counter(f"{human[i][0]}->{judge[i][0]}" for i in scored)),
    }


def calibration_items(
    questions: Sequence[Mapping[str, Any]],
    split: Mapping[str, Sequence[str]],
    lines: Sequence[Mapping[str, Any]],
    seed: int = 20261010,
) -> list[dict[str, Any]]:
    """The 15 to grade: drawn from the dev-only judge sample, with the run's stored answer.
    Only what the grader needs; never a check or a verdict."""
    from eval.judge import judge_sample

    ids = calibration_ids(judge_sample(questions, split["dev"]), seed)
    by_q = {q["id"]: q for q in questions}
    answers = {x["id"]: x.get("answer") for x in lines}
    missing = [i for i in ids if not (answers.get(i) or {}).get("text")]
    if missing:
        raise SystemExit(f"the run has no answer for {missing}")
    return [
        {
            "id": i,
            "question": by_q[i]["question"],
            "reference_answer": by_q[i].get("reference_answer", ""),
            "sources": answers[i]["sources"],
            "answer": answers[i]["text"],
        }
        for i in ids
    ]


def main(argv: list[str] | None = None) -> int:
    from eval.dataset import DATASETS, load_questions

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", required=True, help="a generation run's tag in eval/runs/"
    )
    parser.add_argument("--seed", type=int, default=20261010)
    args = parser.parse_args(argv)
    run_dir = ROOT / "eval" / "runs" / args.run
    dataset = json.loads((run_dir / "run.json").read_text())["dataset"]
    split = json.loads((DATASETS / f"{dataset}.split.json").read_text())
    lines = [
        json.loads(x) for x in (run_dir / "results.jsonl").read_text().splitlines()
    ]
    items = calibration_items(load_questions(dataset), split, lines, args.seed)
    out = ROOT / "eval" / "calibration" / f"{args.run}.grades.jsonl"
    grade(items, out)
    human = {
        g["id"]: (g["correctness"], g["faithful"])
        for g in map(json.loads, out.read_text().splitlines())
    }
    verdicts = {
        x["id"]: (
            x["answer"]["verdict"]["correctness"],
            x["answer"]["verdict"]["faithful"],
        )
        for x in lines
        if x.get("answer") and x["answer"].get("verdict")
    }
    print(f"{len(human)}/{len(items)} graded, saved in {out.relative_to(ROOT)}")
    if not verdicts:
        print("the judge has not run on this run yet; no agreement to report")
        return 0
    print(json.dumps(agreement(human, verdicts), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
