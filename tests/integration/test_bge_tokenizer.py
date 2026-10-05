from pathlib import Path

import pytest

from app.providers.tokenizer import BgeTokenizer, is_cached
from app.services.chunking import chunk_markdown

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "long_document.md"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_cached(), reason="BGE tokenizer not cached; run make fetch-models"
    ),
]


def test_real_tokenizer_keeps_every_chunk_within_510_tokens_with_specials() -> None:
    tokenizer = BgeTokenizer()
    markdown = FIXTURE.read_text(encoding="utf-8")

    drafts = chunk_markdown(markdown, tokenizer, max_tokens=350, overlap=50)

    assert drafts
    largest = max(tokenizer.count_with_specials(d.text) for d in drafts)
    print(f"\nchunks={len(drafts)} largest_with_specials={largest} (limit 510)")
    assert largest <= 510
    assert all(d.token_count <= 350 for d in drafts)
    assert tokenizer.special_token_overhead == 2
