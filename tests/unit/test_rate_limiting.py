"""Token-bucket math with a fake clock (M7 rate limiting)."""

import pytest

from app.core.config import Settings
from app.services.rate_limiting import (
    Bucket,
    BucketState,
    buckets_for,
    take,
    take_all,
)

CHAT = Bucket(capacity=5, refill_per_second=1 / 60)


def _drain(bucket: Bucket, n: int, now: float = 0.0) -> BucketState | None:
    state: BucketState | None = None
    for _ in range(n):
        decision, state = take(state, bucket, now)
        assert decision.allowed
    return state


def test_a_full_bucket_allows_a_burst_up_to_capacity_then_denies() -> None:
    state = _drain(CHAT, 5)

    decision, _ = take(state, CHAT, now=0.0)

    assert not decision.allowed
    assert decision.remaining == 0
    # One token refills in 60 s.
    assert decision.retry_after == pytest.approx(60.0)


def test_tokens_refill_with_time_and_never_exceed_capacity() -> None:
    state = _drain(CHAT, 5)

    later, state_after = take(state, CHAT, now=60.0)
    much_later, _ = take(None, CHAT, now=10_000.0)

    assert later.allowed
    assert state_after.tokens == pytest.approx(0.0)
    assert much_later.remaining == pytest.approx(4.0)  # capped at 5, minus this one


def test_retry_after_shrinks_as_time_passes() -> None:
    state = _drain(CHAT, 5)

    decision, _ = take(state, CHAT, now=45.0)

    assert not decision.allowed
    assert decision.retry_after == pytest.approx(15.0)


def test_a_denied_take_consumes_nothing() -> None:
    state = _drain(CHAT, 5)

    _, after_denial = take(state, CHAT, now=0.0)
    decision, _ = take(after_denial, CHAT, now=60.0)

    assert decision.allowed


def test_take_all_is_all_or_nothing_across_tenant_and_user_buckets() -> None:
    tenant = Bucket(capacity=4, refill_per_second=0.0)
    user = Bucket(capacity=2, refill_per_second=0.0)
    states: list[BucketState | None] = [None, None]

    results = []
    for _ in range(3):
        decision, new_states = take_all(states, [tenant, user], now=0.0)
        states = [*new_states]
        results.append(decision.allowed)

    assert results == [True, True, False]
    # The user's denial took nothing from the tenant: 2 of 4 tenant tokens are left.
    assert states[0] is not None and states[0].tokens == pytest.approx(2.0)


def test_a_bucket_that_never_refills_reports_no_finite_retry() -> None:
    frozen = Bucket(capacity=1, refill_per_second=0.0)
    state = _drain(frozen, 1)

    decision, _ = take(state, frozen, now=0.0)

    assert not decision.allowed
    assert decision.retry_after == float("inf")


def test_buckets_follow_your_m7_limits_and_users_get_half() -> None:
    settings = Settings(_env_file=None)

    chat_tenant, chat_user = buckets_for("chat", settings)
    search_tenant, _ = buckets_for("search", settings)
    default_tenant, default_user = buckets_for("default", settings)

    assert chat_tenant.capacity == 5
    assert chat_tenant.refill_per_second == pytest.approx(1 / 60)
    assert chat_user.capacity == 2.5
    assert chat_user.refill_per_second == pytest.approx(1 / 120)
    assert search_tenant.capacity == 20
    assert search_tenant.refill_per_second == pytest.approx(0.2)
    assert default_tenant.capacity == 120
    assert default_tenant.refill_per_second == 2.0
    assert default_user.capacity == 60
