"""Redis token buckets (M7). One Lua script checks and charges every key atomically.

Same algorithm as app/services/rate_limiting.take_all, using Redis's own clock (TIME), so
every API process agrees on time and no request can overspend between a read and a write.
"""

import math
from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.services.rate_limiting import Bucket, Decision

# KEYS: bucket keys. ARGV: cost, then capacity and refill_per_second for each key.
# Returns {allowed (0/1), remaining, retry_after (-1 = never)} as strings.
_TAKE = """
local cost = tonumber(ARGV[1])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local tokens = {}
local allowed = 1
for i = 1, #KEYS do
  local capacity = tonumber(ARGV[2 * i])
  local rate = tonumber(ARGV[2 * i + 1])
  local saved = redis.call('HMGET', KEYS[i], 't', 'u')
  local current = capacity
  if saved[1] then
    local elapsed = math.max(0, now - tonumber(saved[2]))
    current = math.min(capacity, tonumber(saved[1]) + elapsed * rate)
  end
  tokens[i] = current
  if current < cost then allowed = 0 end
end
local remaining = nil
local wait = 0
for i = 1, #KEYS do
  local capacity = tonumber(ARGV[2 * i])
  local rate = tonumber(ARGV[2 * i + 1])
  if allowed == 1 then tokens[i] = tokens[i] - cost end
  if remaining == nil or tokens[i] < remaining then remaining = tokens[i] end
  if allowed == 0 and tokens[i] < cost then
    if rate <= 0 then
      wait = -1
    elseif wait >= 0 then
      wait = math.max(wait, (cost - tokens[i]) / rate)
    end
  end
  redis.call('HSET', KEYS[i], 't', tostring(tokens[i]), 'u', tostring(now))
  if rate > 0 then
    redis.call('EXPIRE', KEYS[i], math.ceil(capacity / rate) + 60)
  else
    redis.call('EXPIRE', KEYS[i], 86400)
  end
end
return {allowed, tostring(remaining), tostring(wait)}
"""


# KEYS: bucket keys. ARGV: cost, then each key's capacity. Adds the cost back, capped at
# capacity; a key that no longer exists is left alone.
_REFUND = """
local cost = tonumber(ARGV[1])
for i = 1, #KEYS do
  local tokens = redis.call('HGET', KEYS[i], 't')
  if tokens then
    local capacity = tonumber(ARGV[i + 1])
    redis.call('HSET', KEYS[i], 't', tostring(math.min(capacity, tonumber(tokens) + cost)))
  end
end
return 1
"""


class RateLimiterUnavailable(Exception):
    """Redis couldn't be reached; the caller decides whether to fail open or closed."""


class RedisRateLimitStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_TAKE)
        self._refund = redis.register_script(_REFUND)

    async def take(
        self, keys: Sequence[str], buckets: Sequence[Bucket], cost: float = 1.0
    ) -> Decision:
        args: list[Any] = [cost]
        for bucket in buckets:
            args += [bucket.capacity, bucket.refill_per_second]
        try:
            allowed, remaining, wait = await self._script(keys=list(keys), args=args)
            retry_after = float(wait)
            decision = Decision(
                allowed=int(allowed) == 1,
                remaining=float(remaining),
                retry_after=math.inf if retry_after < 0 else retry_after,
            )
        except (RedisError, OSError, TimeoutError) as exc:
            raise RateLimiterUnavailable(type(exc).__name__) from exc
        except (ValueError, TypeError, IndexError) as exc:
            # A reply we can't read is no answer at all: same fail-open/closed rules.
            raise RateLimiterUnavailable(
                f"malformed reply ({type(exc).__name__})"
            ) from exc
        return decision

    async def refund(
        self, keys: Sequence[str], buckets: Sequence[Bucket], cost: float = 1.0
    ) -> None:
        """Give back what take() charged (ADR-0010: a 422 costs nothing)."""
        args: list[Any] = [cost, *(bucket.capacity for bucket in buckets)]
        try:
            await self._refund(keys=list(keys), args=args)
        except (RedisError, OSError, TimeoutError) as exc:
            raise RateLimiterUnavailable(type(exc).__name__) from exc
