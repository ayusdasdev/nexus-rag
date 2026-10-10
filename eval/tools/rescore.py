"""Re-score a generation run's stored answers with the current checks (M8).

    uv run python -m eval.tools.rescore --run E3-gen

Nothing is generated and no model is loaded. Two re-scorings of the same answers:
- checks_fixed: the stored final text, current deterministic checks. The difference from
  the run's own summary.json is the effect of the check fixes alone.
- checks_fixed_and_recleaned: the stored raw model output re-run through the app's
  current answer cleanup (parse_citations, strip_prompt_scaffolding) first, so the
  cleanup's effect shows on the same answers.
results.jsonl and summary.json are never changed; the report goes to rescore.json.
"""

import argparse
import copy
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.services.chat import REFUSAL
from app.services.generation import parse_citations, strip_prompt_scaffolding
from eval.runner import _checks, summarise_generation

ROOT = Path(__file__).resolve().parents[2]


def _reclean(answer: dict[str, Any]) -> dict[str, Any]:
    """The app's post-processing (app.services.chat.answer_events) on the raw output."""
    citations = parse_citations(answer["raw_text"], source_count=len(answer["sources"]))
    text = strip_prompt_scaffolding(citations.text)
    return {
        **answer,
        "text": text,
        "cited": citations.numbers,
        "dropped": citations.dropped,
        "malformed": citations.malformed,
        "refused": text == REFUSAL,
    }


def rescore_lines(
    lines: Sequence[dict[str, Any]],
    questions: Sequence[dict[str, Any]],
    holdout_ids: Sequence[str],
    reclean: bool = False,
) -> list[dict[str, Any]]:
    """New lines with current checks. The input lines are never modified."""
    held = sorted({x["id"] for x in lines} & set(holdout_ids))
    if held:
        raise SystemExit(f"refusing to re-score hold-out questions: {held}")
    by_id = {q["id"]: q for q in questions}
    out = []
    for line in lines:
        new = copy.deepcopy(line)
        answer = new.get("answer")
        if answer is not None and answer.get("text") is not None and reclean:
            answer = new["answer"] = _reclean(answer)
        new["checks"] = _checks(by_id[line["id"]], answer)
        out.append(new)
    return out


def _flat(checks: dict[str, Any] | None) -> dict[str, Any]:
    return {
        f"{group}.{key}": value
        for group, values in (checks or {}).items()
        for key, value in values.items()
    }


def _changed(
    old: Sequence[dict[str, Any]], new: Sequence[dict[str, Any]]
) -> dict[str, list[str]]:
    """Per question, the check fields whose value changed. A field the old checks didn't
    have counts as changed only when it isn't empty."""
    out = {}
    for before, after in zip(old, new, strict=True):
        a, b = _flat(before["checks"]), _flat(after["checks"])
        keys = [k for k in b if a.get(k, [] if b[k] == [] else None) != b[k]]
        if keys:
            out[before["id"]] = keys
    return out


def _summaries(lines: Sequence[dict[str, Any]]) -> dict[str, Any]:
    types = sorted({x["type"] for x in lines})
    return {
        "generation": summarise_generation(lines),
        "generation_per_type": {
            t: summarise_generation([x for x in lines if x["type"] == t]) for t in types
        },
    }


def rescore_run(
    run_dir: Path,
    questions: Sequence[dict[str, Any]],
    holdout_ids: Sequence[str],
) -> dict[str, Any]:
    lines = [
        json.loads(x) for x in (run_dir / "results.jsonl").read_text().splitlines()
    ]
    old = json.loads((run_dir / "summary.json").read_text())
    fixed = rescore_lines(lines, questions, holdout_ids)
    recleaned = rescore_lines(lines, questions, holdout_ids, reclean=True)
    report = {
        "old": {k: old[k] for k in ("generation", "generation_per_type")},
        "checks_fixed": _summaries(fixed),
        "checks_fixed_and_recleaned": _summaries(recleaned),
        "changed": {
            "checks_fixed": _changed(lines, fixed),
            "checks_fixed_and_recleaned": _changed(lines, recleaned),
        },
        "malformed": {
            x["id"]: x["checks"]["citations"]["malformed"]
            for x in recleaned
            if x["checks"] and x["checks"]["citations"]["malformed"]
        },
        "recleaned_text_changed": [
            a["id"]
            for a, b in zip(lines, recleaned, strict=True)
            if a.get("answer") and a["answer"]["text"] != b["answer"]["text"]
        ],
    }
    (run_dir / "rescore.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    from eval.dataset import DATASETS, load_questions

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="a generation run's tag")
    args = parser.parse_args(argv)
    run_dir = ROOT / "eval" / "runs" / args.run
    dataset = json.loads((run_dir / "run.json").read_text())["dataset"]
    split = json.loads((DATASETS / f"{dataset}.split.json").read_text())
    report = rescore_run(run_dir, load_questions(dataset), split["holdout"])
    print(json.dumps({k: report[k] for k in ("changed", "malformed")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
