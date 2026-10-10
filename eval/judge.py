"""Answer grading for M8 (guide 8.4).

Deterministic checks run on every answer: refusal accuracy against the exact refusal
sentence, citation validity, and a reference-fact check on the reference answer's numbers
and identifiers. The one-call LLM judge (llama3.2:3b in practice, any LLMProvider here)
grades correctness 0-1-2 and faithfulness on the fixed 20-question dev sample. A small
local judge gives rough numbers; it is calibrated against your hand grades
(eval/tools/calibrate.py) and reported as such.
"""

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.providers.llm import ChatMessage, LLMError, LLMProvider
from app.services.chat import REFUSAL

PROMPTS = Path(__file__).resolve().parent / "prompts"
JUDGE_SAMPLE_SEED = 20261010
JUDGE_SAMPLE_SIZE = 20
_NAME = re.compile(r"[a-z_]{1,64}")
_SLOT = re.compile(r"\{\{(question|reference|sources|answer)\}\}")
# Phrases a paraphrased refusal tends to use; flagged, never counted as a refusal.
_NEAR_REFUSAL = re.compile(
    r"\b(can ?not|can't|unable to|not able to) (answer|find)|"
    r"\b(not|no information) (in|from) the (provided )?(documents|sources|context)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnswerRecord:
    qid: str
    question: str
    answerable: bool
    reference_answer: str
    gold_spans: list[str]
    answer: str
    cited: list[int]
    dropped: list[int]
    sources: list[str]


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# --- deterministic checks -----------------------------------------------------------


def refusal_check(rec: AnswerRecord) -> dict[str, Any]:
    refused = rec.answer.strip() == REFUSAL
    if rec.answerable:
        outcome = "false_refusal" if refused else "answered"
    else:
        outcome = "correct_refusal" if refused else "missed_refusal"
    near = not refused and bool(_NEAR_REFUSAL.search(rec.answer))
    return {"refused": refused, "outcome": outcome, "near_refusal": near}


def citation_check(rec: AnswerRecord) -> dict[str, Any]:
    valid, invalid = len(rec.cited), len(rec.dropped)
    cites_gold: bool | None = None
    if rec.answerable:
        spans = [_ws(s) for s in rec.gold_spans]
        cited_texts = [
            _ws(rec.sources[n - 1]) for n in rec.cited if 1 <= n <= len(rec.sources)
        ]
        cites_gold = any(span in text for span in spans for text in cited_texts)
    return {
        "valid": valid,
        "invalid": invalid,
        "validity": valid / (valid + invalid) if valid + invalid else None,
        "cites_gold": cites_gold,
    }


_UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = {
    w: 10 * i
    for i, w in enumerate(
        [
            "_",
            "_",
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
        ]
    )
    if w != "_"
}
_NUMBER_WORD = re.compile(
    rf"\b(?:({'|'.join(_TENS)})(?:[- ]({'|'.join(_UNITS[1:10])}))?|({'|'.join(_UNITS)}))\b"
)


def _digits(text: str) -> str:
    def value(m: re.Match[str]) -> str:
        if m.group(3):
            return str(_UNITS.index(m.group(3)))
        return str(_TENS[m.group(1)] + (_UNITS.index(m.group(2)) if m.group(2) else 0))

    return _NUMBER_WORD.sub(value, text)


def _norm_facts(text: str) -> str:
    return _digits(_ws(text).replace("–", "-").replace("—", "-"))


def key_facts(reference: str) -> list[str]:
    """Checkable facts: tokens with a digit or underscore, and all-caps words (IDF)."""
    facts: list[str] = []
    for raw in re.findall(
        r"[A-Za-z0-9_][A-Za-z0-9_.,:\-']*", reference.replace("–", "-")
    ):
        token = re.sub(r"'s$", "", raw.rstrip(".,:;'-"))
        checkable = re.search(r"[0-9_]", token) or re.fullmatch(r"[A-Z]{2,}", token)
        if checkable and token.lower() not in facts:
            facts.append(token.lower())
    return facts


def fact_check(rec: AnswerRecord) -> dict[str, Any]:
    facts = key_facts(rec.reference_answer) if rec.answerable else []
    answer = _norm_facts(rec.answer)
    found = [
        f
        for f in facts
        if re.search(rf"(?<![0-9a-z_]){re.escape(f)}(?![0-9a-z_])", answer)
    ]
    return {
        "facts": facts,
        "found": found,
        "share": len(found) / len(facts) if facts else None,
    }


def deterministic_checks(rec: AnswerRecord) -> dict[str, Any]:
    return {
        "refusal": refusal_check(rec),
        "citations": citation_check(rec),
        "facts": fact_check(rec),
    }


# --- the LLM judge ------------------------------------------------------------------


def load_judge_prompt(name: str) -> str:
    """eval/prompts/<name>.md. name is a bare identifier, never a path."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid prompt name: {name!r}")
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def _escape(text: str) -> str:
    # Graded text can't open or close the judge's own sections.
    return text.replace("<", "&lt;")


def parse_verdict(text: str) -> dict[str, Any]:
    """The first JSON object in text, checked field by field; anything else is a ValueError."""
    decoder = json.JSONDecoder()
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        correctness, faithful = obj.get("correctness"), obj.get("faithful")
        claims = obj.get("unsupported_claims")
        if (
            type(correctness) is not int
            or correctness not in (0, 1, 2)
            or type(faithful) is not bool
            or not isinstance(claims, list)
            or not all(isinstance(c, str) for c in claims)
        ):
            raise ValueError(f"invalid verdict fields: {obj!r}")
        return {
            "correctness": correctness,
            "faithful": faithful,
            "unsupported_claims": claims,
        }
    raise ValueError("no JSON object in the judge's reply")


def judge_messages(rec: AnswerRecord) -> list[ChatMessage]:
    sources = "\n\n".join(
        f"<source id='{n}'>\n{_escape(text)}\n</source>"
        for n, text in enumerate(rec.sources, 1)
    )
    values = {
        "question": _escape(rec.question),
        "reference": _escape(
            rec.reference_answer or "(none: the documents don't answer this)"
        ),
        "sources": sources or "(no sources were retrieved)",
        "answer": _escape(rec.answer),
    }
    user = _SLOT.sub(lambda m: values[m.group(1)], load_judge_prompt("judge_user"))
    return [
        ChatMessage(role="system", content=load_judge_prompt("judge_system")),
        ChatMessage(role="user", content=user),
    ]


async def llm_judge(llm: LLMProvider, rec: AnswerRecord) -> dict[str, Any]:
    """One call, temperature 0. A failed call or an unreadable reply is an error, not a score."""
    empty: dict[str, Any] = {
        "correctness": None,
        "faithful": None,
        "unsupported_claims": None,
    }
    try:
        reply = await llm.complete(judge_messages(rec), max_tokens=300, temperature=0.0)
    except LLMError as exc:
        return {**empty, "error": f"llm_error:{type(exc).__name__}", "judge": llm.name}
    try:
        verdict = parse_verdict(reply)
    except ValueError:
        return {**empty, "error": "unparseable", "judge": llm.name}
    return {**verdict, "error": None, "judge": llm.name}


def judge_sample(
    questions: Sequence[dict[str, Any]],
    dev_ids: Sequence[str],
    seed: int = JUDGE_SAMPLE_SEED,
    size: int = JUDGE_SAMPLE_SIZE,
) -> list[str]:
    """size dev questions, per type in proportion (largest remainder), seeded. Never hold-out."""
    dev = set(dev_ids)
    by_type: dict[str, list[str]] = {}
    for q in questions:
        if q["id"] in dev:
            by_type.setdefault(q["type"], []).append(q["id"])
    kinds = sorted(by_type)
    exact = {k: size * len(by_type[k]) / len(dev) for k in kinds}
    counts = {k: int(exact[k]) for k in kinds}
    for k in sorted(kinds, key=lambda k: (-(exact[k] - counts[k]), k))[
        : size - sum(counts.values())
    ]:
        counts[k] += 1
    rng = random.Random(seed)
    chosen: list[str] = []
    for k in kinds:
        chosen += rng.sample(sorted(by_type[k]), counts[k])
    return sorted(chosen)
