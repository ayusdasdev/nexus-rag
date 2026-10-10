"""Token-bucket rate limiting (M7): pure math, so it can be tested with a fake clock.

Each request takes one token from its tenant's bucket AND its user's bucket (half the
tenant's limits). Both must have a token, or neither is charged. The Redis store runs the
same algorithm atomically (app/repositories/rate_limit_store.py).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings

LimitClass = Literal["chat", "search", "upload", "default"]


@dataclass(frozen=True)
class Bucket:
    capacity: float
    refill_per_second: float


@dataclass(frozen=True)
class BucketState:
    tokens: float
    updated_at: float


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: float
    # Seconds until the request could succeed; 0 when allowed, inf if it never refills.
    retry_after: float


def _refilled(state: BucketState | None, bucket: Bucket, now: float) -> float:
    if state is None:
        return bucket.capacity
    elapsed = max(0.0, now - state.updated_at)
    return min(bucket.capacity, state.tokens + elapsed * bucket.refill_per_second)


def _wait(tokens: float, bucket: Bucket, cost: float) -> float:
    if tokens >= cost:
        return 0.0
    if bucket.refill_per_second <= 0:
        return math.inf
    return (cost - tokens) / bucket.refill_per_second


def take(
    state: BucketState | None, bucket: Bucket, now: float, cost: float = 1.0
) -> tuple[Decision, BucketState]:
    decision, (new_state,) = take_all([state], [bucket], now, cost)
    return decision, new_state


def take_all(
    states: Sequence[BucketState | None],
    buckets: Sequence[Bucket],
    now: float,
    cost: float = 1.0,
) -> tuple[Decision, list[BucketState]]:
    """Charge every bucket, or none of them if any is short."""
    tokens = [_refilled(s, b, now) for s, b in zip(states, buckets, strict=True)]
    allowed = all(t >= cost for t in tokens)
    if allowed:
        tokens = [t - cost for t in tokens]
    retry_after = (
        0.0
        if allowed
        else max(_wait(t, b, cost) for t, b in zip(tokens, buckets, strict=True))
    )
    return (
        Decision(allowed=allowed, remaining=min(tokens), retry_after=retry_after),
        [BucketState(tokens=t, updated_at=now) for t in tokens],
    )


def buckets_for(kind: LimitClass, settings: Settings) -> tuple[Bucket, Bucket]:
    """(tenant bucket, user bucket) for a route class; a user gets half the tenant's."""
    capacity, refill = {
        "chat": (
            settings.rate_limit_chat_capacity,
            settings.rate_limit_chat_refill_per_second,
        ),
        "search": (
            settings.rate_limit_search_capacity,
            settings.rate_limit_search_refill_per_second,
        ),
        "upload": (
            settings.rate_limit_upload_capacity,
            settings.rate_limit_upload_refill_per_second,
        ),
        "default": (
            settings.rate_limit_default_capacity,
            settings.rate_limit_default_refill_per_second,
        ),
    }[kind]
    return Bucket(capacity, refill), Bucket(capacity / 2, refill / 2)
