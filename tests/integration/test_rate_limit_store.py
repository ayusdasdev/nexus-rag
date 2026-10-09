"""The Redis token-bucket store against a real Redis (M7). No fakeredis."""

import asyncio
import math
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import get_settings
from app.repositories.rate_limit_store import (
    RateLimiterUnavailable,
    RedisRateLimitStore,
)
from app.services.rate_limiting import Bucket

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_settings().redis_url)
    try:
        yield client
    finally:
        await client.aclose()


def _keys(n: int = 1) -> list[str]:
    return [f"rl:test:{uuid.uuid4().hex}" for _ in range(n)]


async def test_a_burst_up_to_capacity_then_denied(redis: Redis) -> None:
    store = RedisRateLimitStore(redis)
    keys, bucket = _keys(), [Bucket(capacity=3, refill_per_second=0.0)]

    results = [(await store.take(keys, bucket)).allowed for _ in range(4)]
    denied = await store.take(keys, bucket)

    assert results == [True, True, True, False]
    assert denied.remaining == pytest.approx(0.0)
    assert denied.retry_after == math.inf


async def test_tokens_refill_over_time(redis: Redis) -> None:
    store = RedisRateLimitStore(redis)
    keys, bucket = _keys(), [Bucket(capacity=1, refill_per_second=20.0)]

    first = await store.take(keys, bucket)
    second = await store.take(keys, bucket)
    await asyncio.sleep(0.3)  # 20/s refills a token in 0.05 s; 6x margin
    third = await store.take(keys, bucket)

    assert (first.allowed, second.allowed, third.allowed) == (True, False, True)
    assert 0 < second.retry_after <= 0.05 + 1e-6


async def test_tenant_and_user_buckets_are_charged_all_or_nothing(redis: Redis) -> None:
    store = RedisRateLimitStore(redis)
    keys = _keys(2)
    buckets = [
        Bucket(capacity=4, refill_per_second=0.0),
        Bucket(capacity=2, refill_per_second=0.0),
    ]

    results = [(await store.take(keys, buckets)).allowed for _ in range(3)]
    tenant_tokens = float(await redis.hget(keys[0], "t") or 0)

    assert results == [True, True, False]
    assert tenant_tokens == pytest.approx(2.0)


async def test_separate_keys_have_separate_buckets(redis: Redis) -> None:
    store = RedisRateLimitStore(redis)
    bucket = [Bucket(capacity=1, refill_per_second=0.0)]
    tenant_a, tenant_b = _keys(), _keys()

    assert (await store.take(tenant_a, bucket)).allowed
    assert not (await store.take(tenant_a, bucket)).allowed
    assert (await store.take(tenant_b, bucket)).allowed


async def test_buckets_expire_once_they_would_be_full_again(redis: Redis) -> None:
    store = RedisRateLimitStore(redis)
    keys = _keys()

    await store.take(keys, [Bucket(capacity=5, refill_per_second=1.0)])
    ttl = await redis.ttl(keys[0])

    assert 0 < ttl <= 5 + 60


async def test_concurrent_takes_never_overspend(redis: Redis) -> None:
    store = RedisRateLimitStore(redis)
    keys, bucket = _keys(), [Bucket(capacity=10, refill_per_second=0.0)]

    decisions = await asyncio.gather(*(store.take(keys, bucket) for _ in range(30)))

    assert sum(d.allowed for d in decisions) == 10


async def test_an_unreachable_redis_is_a_typed_error() -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)
    try:
        with pytest.raises(RateLimiterUnavailable):
            await RedisRateLimitStore(dead).take(_keys(), [Bucket(1, 0.0)])
    finally:
        await dead.aclose()
