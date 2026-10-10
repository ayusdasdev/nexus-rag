"""Rate-limit dependencies (M7): per-tenant and per-user token buckets in Redis.

Keys come only from the verified token (tenant_id, user id), never from IP or forwarding
headers, so a client can't move itself to a fresh bucket. Runs after authentication: an
unauthenticated request is a 401 and spends nothing. With Redis down, chat (LLM cost) fails
closed with 503 and every other class fails open.
"""

import hashlib
import logging
import math
from collections.abc import Awaitable, Callable
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from app.api.client_ip import client_ip
from app.api.deps import CurrentUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.redis import get_redis_client
from app.repositories.rate_limit_store import (
    RateLimiterUnavailable,
    RedisRateLimitStore,
)
from app.services.rate_limiting import Bucket, LimitClass, buckets_for

logger = logging.getLogger(__name__)

# A bucket that never refills would say "retry in infinity"; tell the client one day.
_MAX_RETRY_AFTER = 86400


@lru_cache
def get_rate_limit_store() -> RedisRateLimitStore:
    return RedisRateLimitStore(get_redis_client())


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _too_many(retry: float, limit: float) -> HTTPException:
    retry_after = _MAX_RETRY_AFTER if math.isinf(retry) else math.ceil(retry)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={
            "Retry-After": str(min(retry_after, _MAX_RETRY_AFTER)),
            "X-RateLimit-Limit": _number(limit),
            "X-RateLimit-Remaining": "0",
        },
    )


def rate_limited(kind: LimitClass) -> Callable[..., Awaitable[None]]:
    async def check(
        user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
        settings: Settings = Depends(get_settings),  # noqa: B008 - FastAPI DI pattern
        store: RedisRateLimitStore = Depends(get_rate_limit_store),  # noqa: B008
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        tenant_bucket, user_bucket = buckets_for(kind, settings)
        keys = [f"rl:{kind}:tenant:{user.tenant_id}", f"rl:{kind}:user:{user.id}"]
        try:
            decision = await store.take(keys, [tenant_bucket, user_bucket])
        except RateLimiterUnavailable as exc:
            if kind == "chat":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Rate limiting is unavailable; try again later",
                ) from exc
            logger.warning("rate limiter unavailable (%s); allowing %s", exc, kind)
            return
        if not decision.allowed:
            raise _too_many(decision.retry_after, tenant_bucket.capacity)

    check.__name__ = f"rate_limited_{kind}"
    return check


limit_chat = rate_limited("chat")
limit_search = rate_limited("search")
limit_default = rate_limited("default")


async def enforce_auth_limit(
    kind: str,
    request: Request,
    settings: Settings,
    store: RedisRateLimitStore,
    email: str | None = None,
) -> None:
    """Signup: per client IP + a global budget. Login: per client IP + per email.

    Called after the body is validated and before any password hashing. Fails closed:
    with Redis down, credential endpoints answer 503 rather than run unlimited.
    """
    if not settings.rate_limit_enabled:
        return
    ip = client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        settings.trusted_proxies,
    )
    if kind == "signup":
        keys = [f"rl:signup:ip:{ip}", "rl:signup:global"]
        buckets = [
            Bucket(
                settings.rate_limit_signup_ip_capacity,
                settings.rate_limit_signup_ip_refill_per_second,
            ),
            Bucket(
                settings.rate_limit_signup_global_capacity,
                settings.rate_limit_signup_global_refill_per_second,
            ),
        ]
    else:
        # The email is hashed so no addresses are stored in Redis keys.
        digest = hashlib.sha256((email or "").strip().lower().encode()).hexdigest()
        keys = [f"rl:login:ip:{ip}", f"rl:login:email:{digest}"]
        buckets = [
            Bucket(
                settings.rate_limit_login_ip_capacity,
                settings.rate_limit_login_ip_refill_per_second,
            ),
            Bucket(
                settings.rate_limit_login_email_capacity,
                settings.rate_limit_login_email_refill_per_second,
            ),
        ]
    try:
        decision = await store.take(keys, buckets)
    except RateLimiterUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiting is unavailable; try again later",
        ) from exc
    if not decision.allowed:
        raise _too_many(decision.retry_after, min(b.capacity for b in buckets))
