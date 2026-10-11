"""Run the one-call LLM judge on a generation run's fixed 20-question sample (M8, guide 8.4).

    uv run python -m eval.tools.judge_run --run E3-gen

Grades the stored answers only: nothing is regenerated. The sample is the dev-only
judge_sample; a hold-out id stops the run. Each verdict (with the judge's raw reply and how
long the call took) is appended to eval/runs/<run>/judge.jsonl and flushed as soon as it
finishes, so a crash loses at most the call in flight, and a re-run skips what is there.
The judge never reads eval/calibration/. Ollama only, like eval generation.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.providers.llm import LLMProvider
from eval.judge import answer_record, judge_sample, llm_judge
from eval.metrics import mean

ROOT = Path(__file__).resolve().parents[2]


def check_provider(settings: Settings) -> None:
    if settings.llm_provider != "ollama":
        raise SystemExit(
            f"the eval judge runs on ollama only; LLM_PROVIDER is {settings.llm_provider!r}"
        )


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


async def judge_run(
    run_dir: Path,
    questions: Sequence[dict[str, Any]],
    split: Mapping[str, Sequence[str]],
    llm: LLMProvider,
) -> list[dict[str, Any]]:
    """Judge every sample answer not yet in judge.jsonl; return all verdicts, sample order."""
    ids = judge_sample(questions, split["dev"])
    held = sorted(set(ids) & set(split["holdout"]))
    if held:
        raise SystemExit(f"refusing to judge hold-out questions: {held}")
    by_q = {q["id"]: q for q in questions}
    answers = {x["id"]: x.get("answer") for x in _read(run_dir / "results.jsonl")}
    missing = [i for i in ids if not (answers.get(i) or {}).get("text")]
    if missing:
        raise SystemExit(f"the run has no answer for {missing}")
    out = run_dir / "judge.jsonl"
    done = {v["id"]: v for v in _read(out)}
    with out.open("a") as f:
        for i in ids:
            if i in done:
                continue
            answer = answers[i]
            assert answer is not None
            started = time.perf_counter()
            verdict = await llm_judge(llm, answer_record(by_q[i], answer))
            line = {"id": i, **verdict, "ms": (time.perf_counter() - started) * 1000}
            f.write(json.dumps(line) + "\n")
            f.flush()
            done[i] = line
    return [done[i] for i in ids]


def rough_scores(
    verdicts: Sequence[Mapping[str, Any]], answerable: Mapping[str, bool]
) -> dict[str, Any]:
    """Counts of the judge's own scores (not calibrated); errors counted, never scored."""

    def block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        scored = [v for v in rows if v.get("error") is None]
        grades = Counter(v["correctness"] for v in scored)
        faithful = Counter(v["faithful"] for v in scored)
        return {
            "n": len(scored),
            "correctness": {str(g): grades[g] for g in (0, 1, 2)},
            "mean_correctness": mean([float(v["correctness"]) for v in scored]),
            "faithful": {"true": faithful[True], "false": faithful[False]},
        }

    return {
        "n": len(verdicts),
        "errors": dict(Counter(v["error"] for v in verdicts if v.get("error"))),
        "all": block(verdicts),
        "answerable": block([v for v in verdicts if answerable[v["id"]]]),
        "unanswerable": block([v for v in verdicts if not answerable[v["id"]]]),
    }


def main(argv: list[str] | None = None) -> int:
    from app.core.config import get_settings
    from app.providers.llm_factory import build_llm
    from eval.dataset import DATASETS, load_questions

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="a generation run's tag")
    args = parser.parse_args(argv)
    settings = get_settings()
    check_provider(settings)
    run_dir = ROOT / "eval" / "runs" / args.run
    dataset = json.loads((run_dir / "run.json").read_text())["dataset"]
    split = json.loads((DATASETS / f"{dataset}.split.json").read_text())
    questions = load_questions(dataset)
    verdicts = asyncio.run(judge_run(run_dir, questions, split, build_llm(settings)))
    answerable = {q["id"]: bool(q["answerable"]) for q in questions}
    scores = {
        "judge": settings.ollama_model,
        "rough": "uncalibrated scores from a small local judge",
        **rough_scores(verdicts, answerable),
    }
    (run_dir / "judge_summary.json").write_text(json.dumps(scores, indent=1) + "\n")
    print(json.dumps(scores, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
