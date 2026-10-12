"""The M8 experiment runner (guide 8.5).

    uv run python -m eval.runner --tag E0 --split dev --set mode=dense --set rerank=false

Runs each question of a split through the real retrieval pipeline in-process (and, with
--generate, the real answer pipeline), and appends one JSON line per question to
eval/runs/<tag>/results.jsonl as soon as it finishes. Re-running the same tag resumes:
finished questions are skipped, and a different config is refused. run.json records the
config, dataset version, split seed, runner seed, commit hash and timings. The hold-out
split is refused unless --final-holdout is passed.
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from eval.metrics import first_hit_rank, mean, ndcg_at_k, recall_at_k

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "eval" / "runs"
KS = (1, 3, 5, 10)
RUNNER_SEED = 0  # nothing in a run is random; recorded so that stays checkable

Mode = Literal["dense", "sparse", "hybrid"]
ExpandMode = Literal["none", "neighbors"]
AnswerStyle = Literal["cite", "quote_then_cite", "quote_refusal_first"]


@dataclass(frozen=True)
class RunConfig:
    mode: Mode = "hybrid"
    rerank: bool = True
    candidates: int = 40
    expand: ExpandMode = "none"
    limit: int = 10
    # Weighted RRF (M10): the dense list's weight; BM25 stays at 1.0. 1.0 is plain RRF.
    dense_weight: float = 1.0
    # The answer prompt for generation runs (M10), as ANSWER_STYLE.
    answer_style: AnswerStyle = "cite"


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document: str
    chunk_index: int
    # With expand=neighbors: the hit with its neighbors joined around it, as the answer
    # model would see it (retrieval.expanded_text). Otherwise the chunk's own text.
    text: str
    score: float
    neighbor_indexes: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    stages_ms: dict[str, float]
    answer: dict[str, Any] | None = field(default=None)


SearchFn = Callable[[dict[str, Any], RunConfig], Coroutine[Any, Any, SearchResult]]


def parse_overrides(pairs: Sequence[str]) -> RunConfig:
    """--set key=value for mode, rerank, candidates, expand, limit, dense_weight,
    answer_style; anything else is refused."""
    values: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise ValueError(f"--set needs key=value, got {pair!r}")
        if key == "mode":
            if raw not in ("dense", "sparse", "hybrid"):
                raise ValueError(f"mode must be dense, sparse or hybrid, not {raw!r}")
            values[key] = raw
        elif key == "rerank":
            if raw not in ("true", "false"):
                raise ValueError(f"rerank must be true or false, not {raw!r}")
            values[key] = raw == "true"
        elif key in ("candidates", "limit"):
            number = int(raw)
            top = 100 if key == "candidates" else 50
            if not 1 <= number <= top:
                raise ValueError(f"{key} must be 1-{top}, not {number}")
            values[key] = number
        elif key == "dense_weight":
            weight = float(raw)
            if not 0 < weight <= 10:
                raise ValueError(f"dense_weight must be in (0, 10], not {weight}")
            values[key] = weight
        elif key == "answer_style":
            if raw not in ("cite", "quote_then_cite", "quote_refusal_first"):
                raise ValueError(f"unknown answer_style {raw!r}")
            values[key] = raw
        elif key == "expand":
            if raw not in ("none", "neighbors"):
                raise ValueError(f"expand must be none or neighbors, not {raw!r}")
            values[key] = raw
        else:
            raise ValueError(
                f"unknown override {key!r} (chunking changes need a re-ingest)"
            )
    return RunConfig(**values)


def check_split_allowed(split: str, final_holdout: bool) -> None:
    if split == "holdout" and not final_holdout:
        raise SystemExit(
            "refusing --split holdout: held-out results are for the final run only; "
            "pass --final-holdout to run it"
        )


def select_ids(
    split_ids: Sequence[str], ids: str | None, split_name: str = "dev"
) -> list[str]:
    """--ids narrows the chosen split (for smoke tests); an id outside it is refused."""
    if ids is None:
        return list(split_ids)
    chosen = [i.strip() for i in ids.split(",") if i.strip()]
    outside = [i for i in chosen if i not in set(split_ids)]
    if outside:
        raise SystemExit(f"{', '.join(outside)} not in the {split_name} split")
    return chosen


def git_info() -> tuple[str, bool]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout.strip()
    )
    return sha, dirty


def _line(
    question: dict[str, Any], result: SearchResult, total_ms: float
) -> dict[str, Any]:
    texts = [h.text for h in result.hits]
    spans = [g["span"] for g in question["gold"]]
    answerable = bool(question["answerable"])
    return {
        "id": question["id"],
        "type": question["type"],
        "answerable": answerable,
        "gold_mode": question["gold_mode"],
        "first_hit_rank": first_hit_rank(texts, spans) if answerable else None,
        "recall": (
            {
                str(k): recall_at_k(texts, spans, k, mode=question["gold_mode"])
                for k in KS
            }
            if answerable
            else None
        ),
        "ndcg@10": ndcg_at_k(texts, spans, 10) if answerable else None,
        "retrieved": [asdict(h) for h in result.hits],
        "stages_ms": result.stages_ms,
        "total_ms": total_ms,
        "answer": result.answer,
        "checks": _checks(question, result.answer),
    }


def _checks(
    question: dict[str, Any], answer: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Deterministic answer checks; None without an answer (or when generation failed)."""
    if answer is None or answer["text"] is None:
        return None
    from eval.judge import answer_record, deterministic_checks

    return deterministic_checks(answer_record(question, answer))


def summarise_generation(lines: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Counts, not just rates: refusal outcomes, citations, reference facts, errors."""
    generated = [x for x in lines if x.get("answer") is not None]
    checked = [x for x in generated if x["checks"] is not None]
    outcomes = Counter(x["checks"]["refusal"]["outcome"] for x in checked)
    valid = sum(x["checks"]["citations"]["valid"] for x in checked)
    invalid = sum(x["checks"]["citations"]["invalid"] for x in checked)
    answered = [x for x in checked if x["checks"]["refusal"]["outcome"] == "answered"]
    shares = [x["checks"]["facts"]["share"] for x in answered]
    scored = [s for s in shares if s is not None]
    gen_ms = sorted(x["answer"]["generate_ms"] for x in generated)
    return {
        "n": len(generated),
        "errors": dict(
            Counter(x["answer"]["error"] for x in generated if x["answer"]["error"])
        ),
        "answered": outcomes["answered"],
        "correct_refusal": outcomes["correct_refusal"],
        "missed_refusal": outcomes["missed_refusal"],
        "false_refusal": outcomes["false_refusal"],
        # Paraphrased refusals of unanswerables: neither correct nor a plain miss.
        "near_refusal": outcomes["near_refusal"],
        "answered_with_refusal_wording": sum(
            1 for x in answered if x["checks"]["refusal"]["near_refusal"]
        ),
        "citations": {"valid": valid, "invalid": invalid},
        # Lines scored before malformed citations were checked have no such key.
        "answers_with_malformed_citations": sum(
            1 for x in checked if x["checks"]["citations"].get("malformed")
        ),
        "answered_without_citation": sum(
            1 for x in answered if not x["checks"]["citations"]["valid"]
        ),
        "answered_citing_gold": sum(
            1 for x in answered if x["checks"]["citations"]["cites_gold"]
        ),
        "facts": {
            "mean_share": mean(scored),
            "all_found": sum(1 for s in scored if s == 1.0),
            "scorable": len(scored),
        },
        "generate_ms": {
            "p50": gen_ms[len(gen_ms) // 2] if gen_ms else None,
            "max": gen_ms[-1] if gen_ms else None,
        },
    }


def summarise(lines: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Means over answerable questions, with raw counts ("full" = recall 1.0) next to them."""

    def block(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {"n": len(rows)}
        for k in KS:
            values = [r["recall"][str(k)] for r in rows]
            out[f"recall@{k}"] = {
                "mean": mean(values),
                "full": sum(1 for v in values if v == 1.0),
                "n": len(values),
            }
        ranks = [r["first_hit_rank"] for r in rows]
        out["mrr"] = sum(1 / r for r in ranks if r) / len(ranks) if ranks else None
        out["ndcg@10"] = mean([r["ndcg@10"] for r in rows])
        return out

    answerable = [line for line in lines if line["answerable"]]
    types = sorted({line["type"] for line in answerable})
    latencies = sorted(line["total_ms"] for line in lines)
    return {
        "overall": block(answerable),
        "per_type": {
            t: block([x for x in answerable if x["type"] == t]) for t in types
        },
        "unanswerable_n": sum(1 for line in lines if not line["answerable"]),
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else None,
            "p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
            if latencies
            else None,
        },
    }


async def run_questions(
    questions: Sequence[dict[str, Any]],
    ids: Sequence[str],
    config: RunConfig,
    search: SearchFn,
    out_dir: Path,
    meta: dict[str, Any],
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_path, results_path = out_dir / "run.json", out_dir / "results.jsonl"
    if run_path.exists():
        previous = json.loads(run_path.read_text())
        if previous["config"] != asdict(config):
            raise SystemExit(
                f"{out_dir} was run with config {previous['config']}; refusing to resume "
                f"with {asdict(config)} (use a new --tag)"
            )
        info = previous
    else:
        info = {
            **meta,
            "config": asdict(config),
            "runner_seed": RUNNER_SEED,
            "question_ids": list(ids),
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": None,
        }
        run_path.write_text(json.dumps(info, indent=1) + "\n")

    done = set()
    if results_path.exists():
        done = {
            json.loads(line)["id"] for line in results_path.read_text().splitlines()
        }
    by_id = {q["id"]: q for q in questions}
    with results_path.open("a") as results:
        for qid in ids:
            if qid in done:
                continue
            started = time.perf_counter()
            result = await search(by_id[qid], config)
            line = _line(by_id[qid], result, (time.perf_counter() - started) * 1000)
            results.write(json.dumps(line, ensure_ascii=False) + "\n")
            results.flush()

    lines = [json.loads(line) for line in results_path.read_text().splitlines()]
    selected = [x for x in lines if x["id"] in set(ids)]
    summary = summarise(selected)
    if any(x.get("answer") is not None for x in selected):
        types = sorted({x["type"] for x in selected})
        summary["generation"] = summarise_generation(selected)
        summary["generation_per_type"] = {
            t: summarise_generation([x for x in selected if x["type"] == t])
            for t in types
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    info["finished_at"] = datetime.now(UTC).isoformat()
    run_path.write_text(json.dumps(info, indent=1) + "\n")
    return summary


def _recorded_path(path: Path) -> str:
    """How run.json names a file: relative to the repo, or only its name if outside it.
    Never an absolute local path (it would carry the user's home directory)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag", required=True, help="run name, e.g. E0; also its folder"
    )
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--final-holdout", action="store_true")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--dataset", default="v1")
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help="eval tenant state file (default eval/state/eval_tenant.json)",
    )
    parser.add_argument("--generate", action="store_true", help="also generate answers")
    parser.add_argument(
        "--ids", help="comma-separated ids within the split (smoke tests)"
    )
    args = parser.parse_args(argv)
    check_split_allowed(args.split, args.final_holdout)
    config = parse_overrides(args.overrides)

    import eval.pipeline
    from eval.dataset import DATASETS, load_questions

    state = args.state or eval.pipeline.STATE

    questions = load_questions(args.dataset)
    split = json.loads((DATASETS / f"{args.dataset}.split.json").read_text())
    sha, dirty = git_info()
    meta = {
        "dataset": args.dataset,
        "split": args.split,
        "split_seed": split["seed"],
        "git_sha": sha,
        "git_dirty": dirty,
        "generate": args.generate,
        "state": _recorded_path(state),
        "tenant_id": json.loads(state.read_text())["tenant_id"],
    }
    ids = select_ids(split[args.split], args.ids, args.split)
    search, close = eval.pipeline.make_search(generate=args.generate, state=state)

    async def go() -> dict[str, Any]:
        try:
            return await run_questions(
                questions, ids, config, search, RUNS / args.tag, meta
            )
        finally:
            await close()  # in the same event loop the DB engine was used in

    summary = asyncio.run(go())
    print(json.dumps(summary["overall"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
