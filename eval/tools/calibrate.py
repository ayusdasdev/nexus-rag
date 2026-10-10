"""Calibrate the LLM judge against your own grades (M8, guide 8.4).

    uv run python -m eval.tools.calibrate --run E3-gen

Shows 15 answers from the judged sample of a generation run, one at a time: question,
reference, sources and answer. You grade correctness (0/1/2) and faithfulness (y/n). Each
grade is saved as soon as you give it; q quits and a re-run resumes. Then it prints how
often the judge agrees with you. Your grades are the ground truth; the judge never sees them.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", required=True, help="a generation run's tag in eval/runs/"
    )
    parser.add_argument("--seed", type=int, default=20261010)
    args = parser.parse_args(argv)
    lines = [
        json.loads(x)
        for x in (ROOT / "eval" / "runs" / args.run / "results.jsonl")
        .read_text()
        .splitlines()
    ]
    judged = {
        x["id"]: x for x in lines if x.get("answer") and x["answer"].get("verdict")
    }
    if len(judged) < CALIBRATION_SIZE:
        raise SystemExit(
            f"{args.run} has {len(judged)} judged answers; need {CALIBRATION_SIZE}"
        )
    ids = calibration_ids(list(judged), args.seed)
    items = [
        {
            "id": i,
            **{
                k: judged[i]["answer"][k]
                for k in ("question", "reference_answer", "answer", "sources")
            },
        }
        for i in ids
    ]
    out = ROOT / "eval" / "calibration" / f"{args.run}.grades.jsonl"
    grade(items, out)
    human = {
        g["id"]: (g["correctness"], g["faithful"])
        for g in map(json.loads, out.read_text().splitlines())
    }
    verdicts = {
        i: (
            judged[i]["answer"]["verdict"]["correctness"],
            judged[i]["answer"]["verdict"]["faithful"],
        )
        for i in ids
    }
    print(json.dumps(agreement(human, verdicts), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
