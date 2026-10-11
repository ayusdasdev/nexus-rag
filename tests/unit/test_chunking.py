import uuid
from itertools import pairwise
from pathlib import Path

import pytest

from app.core.ids import chunk_id
from app.services.chunking import ChunkDraft, chunk_markdown


class WordTokenizer:
    """One token per whitespace-separated word. Hand-computable, no model needed."""

    model_max_tokens = 512
    special_token_overhead = 0

    def count(self, text: str) -> int:
        return len(text.split())


class WordTokenizerWithSpecials(WordTokenizer):
    special_token_overhead = 2


TOK = WordTokenizer()


def _chunks(md: str, max_tokens: int = 350, overlap: int = 50) -> list[ChunkDraft]:
    return chunk_markdown(md, TOK, max_tokens=max_tokens, overlap=overlap)


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


@pytest.mark.parametrize(
    ("md", "max_tokens", "overlap"),
    [
        (_words(120), 10, 3),
        ("\n\n".join(_words(25, p) for p in "abcdef"), 12, 4),
        ("First sentence here. " * 40, 9, 2),
        ("# Head\n\n" + "x" * 500, 20, 5),
        (
            "| a | b | c |\n|---|---|---|\n"
            + "\n".join("| 1 | 2 | 3 |" for _ in range(30)),
            9,
            4,
        ),
    ],
)
def test_no_chunk_exceeds_max_tokens(md: str, max_tokens: int, overlap: int) -> None:
    drafts = _chunks(md, max_tokens=max_tokens, overlap=overlap)

    assert drafts
    for draft in drafts:
        assert draft.token_count == TOK.count(draft.text)
        assert draft.token_count <= max_tokens


@pytest.mark.parametrize(
    ("md", "expected_paths"),
    [
        (
            "# A\n\nx\n\n## B\n\ny\n\n### C\n\nz\n\n## D\n\nw",
            ["A", "A > B", "A > B > C", "A > D"],
        ),
        ("## Only\n\nbody", ["Only"]),
        ("intro words\n\n# Top\n\nbody", [None, "Top"]),
        ("# A\n\n# B\n\n## C\n\n# D\n\nlast", ["D"]),
    ],
)
def test_heading_path_for_nested_headings(
    md: str, expected_paths: list[str | None]
) -> None:
    drafts = _chunks(md)

    assert [d.heading_path for d in drafts] == expected_paths


def test_consecutive_chunks_in_a_section_overlap() -> None:
    md = _words(40)
    drafts = _chunks(md, max_tokens=10, overlap=3)

    assert len(drafts) > 1
    for prev, cur in pairwise(drafts):
        prev_words = prev.text.split()
        cur_words = cur.text.split()
        shared = [
            n
            for n in range(1, 4)
            if n <= len(prev_words) and cur_words[:n] == prev_words[-n:]
        ]
        assert shared, f"no overlap between {prev.text!r} and {cur.text!r}"


def test_output_is_deterministic_and_ids_are_stable() -> None:
    md = "# A\n\n" + _words(60) + "\n\n## B\n\n" + _words(30, "q")
    document_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    first = _chunks(md, max_tokens=12, overlap=4)
    second = _chunks(md, max_tokens=12, overlap=4)

    assert first == second
    ids_first = [chunk_id(document_id, d.chunk_index) for d in first]
    ids_second = [chunk_id(document_id, d.chunk_index) for d in second]
    assert ids_first == ids_second
    assert len(set(ids_first)) == len(ids_first)


def test_table_that_fits_is_not_split() -> None:
    table = "| Tier | Latency |\n|---|---|\n| Memory | 0.1 ms |\n| Redis | 0.5 ms |"
    md = f"Intro words.\n\n{table}\n\nClosing words."

    drafts = _chunks(md, max_tokens=60, overlap=5)

    assert [d for d in drafts if table in d.text]


def test_table_larger_than_budget_never_splits_a_row() -> None:
    rows = [f"| row{i} | value{i} |" for i in range(30)]
    table = "\n".join(["| name | value |", "|---|---|", *rows])

    drafts = _chunks(table, max_tokens=8, overlap=4)

    for draft in drafts:
        for line in draft.text.split("\n"):
            if line.lstrip().startswith("|"):
                assert line.rstrip().endswith("|"), f"row cut mid-way: {line!r}"
    assert all(any(row in d.text.split("\n") for d in drafts) for row in rows)


def test_empty_sections_are_skipped() -> None:
    md = "# A\n\n## B\n\n# C\n\ntext in C"

    drafts = _chunks(md)

    assert [d.heading_path for d in drafts] == ["C"]


def test_chunks_never_merge_across_sections() -> None:
    md = "# One\n\n" + _words(6, "a") + "\n\n# Two\n\n" + _words(6, "b")

    drafts = _chunks(md, max_tokens=50, overlap=5)

    assert [d.heading_path for d in drafts] == ["One", "Two"]
    assert all("b0" not in d.text for d in drafts if d.heading_path == "One")
    assert all("a0" not in d.text for d in drafts if d.heading_path == "Two")


def test_chunk_index_is_continuous_across_the_document() -> None:
    md = "# A\n\n" + _words(30, "a") + "\n\n# B\n\n" + _words(30, "b")

    drafts = _chunks(md, max_tokens=10, overlap=2)

    assert [d.chunk_index for d in drafts] == list(range(len(drafts)))


def test_fenced_code_hash_lines_are_not_headings() -> None:
    md = "# Real\n\n```bash\n# not a heading\necho hi\n```\n\nafter"

    drafts = _chunks(md)

    assert [d.heading_path for d in drafts] == ["Real"]
    assert "# not a heading" in drafts[0].text


def test_word_longer_than_budget_is_still_capped() -> None:
    md = "x" * 80

    drafts = _chunks(md, max_tokens=5, overlap=1)

    assert all(d.token_count <= 5 for d in drafts)


@pytest.mark.parametrize(
    ("max_tokens", "overlap"),
    [(0, 0), (10, -1), (10, 10), (10, 11)],
)
def test_invalid_parameters_are_rejected(max_tokens: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        _chunks("some words here", max_tokens=max_tokens, overlap=overlap)


@pytest.mark.parametrize(("max_tokens", "should_raise"), [(510, False), (511, True)])
def test_cap_accounts_for_special_token_overhead(
    max_tokens: int, should_raise: bool
) -> None:
    tokenizer = WordTokenizerWithSpecials()
    if should_raise:
        with pytest.raises(ValueError):
            chunk_markdown("some words", tokenizer, max_tokens=max_tokens, overlap=0)
    else:
        chunk_markdown("some words", tokenizer, max_tokens=max_tokens, overlap=0)


# --- chunk_document passes the configured sizes through (M8 E4) ----------------------


def _document(tmp_path: Path) -> Path:
    path = tmp_path / "doc.md"
    paragraphs = [_words(120, prefix=f"p{i}w") for i in range(10)]
    path.write_text("# Title\n\n" + "\n\n".join(paragraphs) + "\n")
    return path


def test_chunk_document_defaults_to_350_and_50(tmp_path: Path) -> None:
    from app.services.ingestion_pipeline import chunk_document

    path = _document(tmp_path)

    default = chunk_document(path, "text/plain", TOK, "structure")
    explicit = chunk_document(
        path, "text/plain", TOK, "structure", max_tokens=350, overlap=50
    )

    assert default == explicit


def test_chunk_document_uses_the_size_it_is_given(tmp_path: Path) -> None:
    from app.services.ingestion_pipeline import chunk_document

    path = _document(tmp_path)

    small = chunk_document(
        path, "text/plain", TOK, "structure", max_tokens=200, overlap=50
    )
    large = chunk_document(
        path, "text/plain", TOK, "structure", max_tokens=500, overlap=50
    )

    assert max(TOK.count(c.text) for c in small) <= 200
    assert max(TOK.count(c.text) for c in large) <= 500
    assert len(small) > len(large)
