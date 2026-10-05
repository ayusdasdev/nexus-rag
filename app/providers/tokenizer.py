import os
import sys
from pathlib import Path

from tokenizers import Tokenizer as HfTokenizer

MODEL_ID = "BAAI/bge-base-en-v1.5"
MODEL_MAX_TOKENS = 512


class TokenizerNotCached(RuntimeError):
    pass


def _hub_cache_dir() -> Path:
    explicit = os.environ.get("HF_HUB_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("HF_HOME", "~/.cache/huggingface")
    return Path(home).expanduser() / "hub"


def cached_tokenizer_file(model_id: str = MODEL_ID) -> Path:
    """Locate tokenizer.json in the local Hugging Face cache. Never touches the network."""
    repo = _hub_cache_dir() / f"models--{model_id.replace('/', '--')}"
    ref = repo / "refs" / "main"
    if not ref.is_file():
        raise TokenizerNotCached(_hint(model_id))
    candidate = repo / "snapshots" / ref.read_text().strip() / "tokenizer.json"
    if not candidate.is_file():
        raise TokenizerNotCached(_hint(model_id))
    return candidate


def is_cached(model_id: str = MODEL_ID) -> bool:
    try:
        cached_tokenizer_file(model_id)
    except TokenizerNotCached:
        return False
    return True


def fetch_tokenizer(model_id: str = MODEL_ID) -> Path:
    """Explicit network download into the Hugging Face cache. Call only from `make fetch-models`."""
    HfTokenizer.from_pretrained(model_id)
    return cached_tokenizer_file(model_id)


def _hint(model_id: str) -> str:
    return (
        f"Tokenizer {model_id} is not in the local cache. "
        "Run `make fetch-models` to download it explicitly."
    )


class BgeTokenizer:
    """Counts content tokens for BAAI/bge-base-en-v1.5. Loads on first use, from cache only."""

    def __init__(self, tokenizer_file: Path | None = None) -> None:
        self._tokenizer_file = tokenizer_file
        self._loaded: HfTokenizer | None = None

    def _tokenizer(self) -> HfTokenizer:
        if self._loaded is None:
            path = self._tokenizer_file or cached_tokenizer_file(MODEL_ID)
            self._loaded = HfTokenizer.from_file(str(path))
        return self._loaded

    @property
    def model_max_tokens(self) -> int:
        return MODEL_MAX_TOKENS

    @property
    def special_token_overhead(self) -> int:
        # [CLS] and [SEP], measured rather than hard-coded.
        return len(self._tokenizer().encode("", add_special_tokens=True).ids)

    def count(self, text: str) -> int:
        return len(self._tokenizer().encode(text, add_special_tokens=False).ids)

    def count_with_specials(self, text: str) -> int:
        return len(self._tokenizer().encode(text, add_special_tokens=True).ids)


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        print(fetch_tokenizer())
    else:
        print("usage: python -m app.providers.tokenizer --fetch", file=sys.stderr)
        sys.exit(2)
