"""Every gold span of every approved v1 question occurs verbatim (whitespace-normalised,
case-sensitive) in its frozen corpus document, as the app's own parser reads it."""

import re
from functools import cache
from pathlib import Path

import pytest

from app.services.parsing import parse
from eval.dataset import CORPUS, load_questions

pytestmark = pytest.mark.integration

CONTENT_TYPES = {".pdf": "application/pdf", ".html": "text/html", ".md": "text/plain"}


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@cache
def _document_text(name: str) -> str:
    path = CORPUS / name
    return _ws(parse(path, CONTENT_TYPES[Path(name).suffix]).markdown)


SPANS = [(q["id"], g["doc"], g["span"]) for q in load_questions() for g in q["gold"]]


@pytest.mark.parametrize(
    "qid,doc,span", SPANS, ids=[f"{s[0]}-{i}" for i, s in enumerate(SPANS)]
)
def test_gold_span_occurs_in_its_frozen_document(qid: str, doc: str, span: str) -> None:
    assert _ws(span) in _document_text(doc), f"{qid}: {span!r} not in {doc}"
