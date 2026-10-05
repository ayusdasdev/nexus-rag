from pathlib import Path

from app.services.chunking import ChunkDraft, Tokenizer, chunk_markdown
from app.services.parsing import parse

MAX_CHUNK_TOKENS = 350
CHUNK_OVERLAP_TOKENS = 50


class ChunkStrategyUnavailable(Exception):
    pass


def chunk_document(
    path: Path, content_type: str, tokenizer: Tokenizer, strategy: str
) -> list[ChunkDraft]:
    if strategy != "structure":
        raise ChunkStrategyUnavailable(strategy)
    parsed = parse(path, content_type)
    return chunk_markdown(
        parsed.markdown,
        tokenizer,
        max_tokens=MAX_CHUNK_TOKENS,
        overlap=CHUNK_OVERLAP_TOKENS,
    )
