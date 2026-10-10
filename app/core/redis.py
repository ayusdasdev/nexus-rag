from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings

# A stalled Redis must fail fast so the rate limiter's fail-open/fail-closed rules apply,
# instead of every request hanging on it (M7 review, MEDIUM-2).
SOCKET_TIMEOUT_SECONDS = 0.5


def make_redis(url: str) -> Redis:
    return Redis.from_url(
        url,
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


@lru_cache
def get_redis_client() -> Redis:
    return make_redis(get_settings().redis_url)
