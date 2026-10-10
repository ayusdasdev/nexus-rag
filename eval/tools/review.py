"""Review candidate eval questions (guide 8.2): k(eep), e(dit), r(eject), q(uit).

    uv run python -m eval.tools.review eval/datasets/candidates.jsonl eval/datasets/v1.jsonl

Decisions are saved after every answer (v1.decisions.json next to the output), so you can
stop and resume. Only kept or edited questions are written to the output, in candidate
order. Editing asks for a new question, gold span and reference answer; Enter keeps each.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main(
    argv: list[str] | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates")
    parser.add_argument("output")
    args = parser.parse_args(argv)
    candidates = _load(Path(args.candidates))
    out = Path(args.output)
    decisions_path = out.with_suffix(".decisions.json")
    decisions: dict[str, str] = (
        json.loads(decisions_path.read_text()) if decisions_path.exists() else {}
    )
    edits: dict[str, dict[str, Any]] = (
        {q["id"]: q for q in _load(out)} if out.exists() else {}
    )

    def ask(prompt: str) -> str:
        stdout.write(prompt)
        stdout.flush()
        return stdin.readline().rstrip("\n")

    for q in candidates:
        if q["id"] in decisions:
            continue
        spans = (
            "; ".join(f"{g['doc']}: {g['span']!r}" for g in q["gold"])
            or "(unanswerable)"
        )
        stdout.write(
            f"\n{q['id']} [{q['type']}]\n  Q: {q['question']}\n  gold ({q['gold_mode']}): "
            f"{spans}\n  ref: {q['reference_answer']}\n"
        )
        choice = ask("k/e/r/q? ").strip().lower()
        if choice in ("q", ""):
            break
        if choice == "e":
            edited = dict(q)
            edited["question"] = ask("question> ") or q["question"]
            if q["gold"]:
                span = ask("first gold span> ")
                if span:
                    edited["gold"] = [{**q["gold"][0], "span": span}, *q["gold"][1:]]
            edited["reference_answer"] = (
                ask("reference answer> ") or q["reference_answer"]
            )
            edits[q["id"]] = {**edited, "edited": True}
            decisions[q["id"]] = "edit"
        elif choice == "k":
            edits[q["id"]] = {**q, "edited": False}
            decisions[q["id"]] = "keep"
        else:
            decisions[q["id"]] = "reject"
        decisions_path.write_text(json.dumps(decisions, indent=1))
        kept = [
            edits[c["id"]]
            for c in candidates
            if decisions.get(c["id"]) in ("keep", "edit")
        ]
        out.write_text("".join(json.dumps(k, ensure_ascii=False) + "\n" for k in kept))
    stdout.write(
        f"\n{sum(v != 'reject' for v in decisions.values())} kept of {len(decisions)} reviewed\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
