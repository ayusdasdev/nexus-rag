"""The linearity check used by the hostile-input tests must catch quadratic code."""

import pytest

from tests.timing import assert_linear


def _linear(text: str) -> int:
    return text.count("a") + len(text.split())


def _quadratic(text: str) -> int:
    # Scans the rest of the string from every position: n^2 / 2 characters in all.
    return sum(text.count("a", i) for i in range(len(text)))


def test_a_linear_function_passes() -> None:
    assert_linear(_linear, lambda n: "a b " * n, 20_000)


def test_a_quadratic_function_fails() -> None:
    with pytest.raises(AssertionError, match="quadratic"):
        assert_linear(_quadratic, lambda n: "a" * n, 10_000)
