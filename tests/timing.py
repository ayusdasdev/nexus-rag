"""A load-independent check that a function's run time grows linearly with its input.

An absolute wall-clock limit fails on a slow or busy machine (a 1.09 s run against a
1.0 s limit, 2026-10-13). Comparing the same function on n and 4n units of input cancels
the machine's speed: linear code takes about 4x as long, quadratic code about 16x.
"""

import time
from collections.abc import Callable

# Between linear (4) and quadratic (16), with room for cache effects and noise.
MAX_RATIO = 10.0
# Each timed batch runs at least this long, so timer resolution and noise don't dominate.
MIN_BATCH_SECONDS = 0.02
ROUNDS = 5


def _best_time(fn: Callable[[str], object], text: str, reps: int, rounds: int) -> float:
    best = float("inf")
    for _ in range(rounds):
        start = time.perf_counter()
        for _ in range(reps):
            fn(text)
        best = min(best, time.perf_counter() - start)
    return best


def assert_linear(
    fn: Callable[[str], object],
    make_input: Callable[[int], str],
    n: int,
    *,
    max_ratio: float = MAX_RATIO,
) -> None:
    """Fail if fn on make_input(4 * n) takes max_ratio times as long as on make_input(n).

    Each size is timed as the best of ROUNDS batches of the same number of calls; the
    batch size grows until the small input takes MIN_BATCH_SECONDS.
    """
    small, large = make_input(n), make_input(4 * n)
    reps = 1
    while _best_time(fn, small, reps, 1) < MIN_BATCH_SECONDS and reps < 1 << 16:
        reps *= 2
    t_small = _best_time(fn, small, reps, ROUNDS)
    t_large = _best_time(fn, large, reps, ROUNDS)
    ratio = t_large / t_small
    assert ratio < max_ratio, (
        f"4x the input took {ratio:.1f}x the time ({t_small:.4f} s -> {t_large:.4f} s "
        f"for {reps} call(s)); linear is about 4x, quadratic about 16x"
    )


def repeat(unit: str) -> Callable[[int], str]:
    """make_input for a hostile run of one unit: repeat(unit)(n) == unit * n."""
    return lambda n: unit * n
