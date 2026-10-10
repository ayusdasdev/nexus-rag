"""A disk cache in front of the reranker (M8): no (model, query, chunk text) pair is ever
scored twice, across experiments and after a crash. Scores are a pure function of those
three, so caching them can't change results."""

import hashlib
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class _Scorer(Protocol):
    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


class CachingReranker:
    def __init__(self, inner: _Scorer, path: Path) -> None:
        self.name = inner.name
        self._inner = inner
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS scores (key TEXT PRIMARY KEY, score REAL)"
        )
        self._db.commit()

    def _key(self, query: str, text: str) -> str:
        return hashlib.sha256(f"{self.name}\0{query}\0{text}".encode()).hexdigest()

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        keys = [self._key(query, t) for t in texts]
        with self._lock:
            found = (
                dict(
                    self._db.execute(
                        f"SELECT key, score FROM scores WHERE key IN ({','.join('?' * len(keys))})",
                        keys,
                    ).fetchall()
                )
                if keys
                else {}
            )
        missing = [i for i, k in enumerate(keys) if k not in found]
        if missing:
            scores = self._inner.score(query, [texts[i] for i in missing])
            with self._lock:
                self._db.executemany(
                    "INSERT OR REPLACE INTO scores VALUES (?, ?)",
                    [(keys[i], s) for i, s in zip(missing, scores, strict=True)],
                )
                self._db.commit()
            found.update({keys[i]: s for i, s in zip(missing, scores, strict=True)})
        return [found[k] for k in keys]
