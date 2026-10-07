import pytest

from app.workers.tasks import (
    PermanentEmbedError,
    batched,
    check_dense_dimension,
    embedding_text,
)


@pytest.mark.parametrize(
    ("heading_path", "with_heading", "expected"),
    [
        ("Guide > Setup", True, "Guide > Setup\nBattery life is 8 hours."),
        ("Guide > Setup", False, "Battery life is 8 hours."),
        (None, True, "Battery life is 8 hours."),
        (None, False, "Battery life is 8 hours."),
    ],
)
def test_embedding_text_prepends_heading_only_when_enabled(
    heading_path: str | None, with_heading: bool, expected: str
) -> None:
    assert (
        embedding_text("Battery life is 8 hours.", heading_path, with_heading)
        == expected
    )


def test_batched_splits_into_fixed_size_groups_keeping_order() -> None:
    assert list(batched(list(range(7)), 3)) == [[0, 1, 2], [3, 4, 5], [6]]


def test_batched_of_empty_yields_nothing() -> None:
    assert list(batched([], 3)) == []


def test_dense_dimension_mismatch_is_a_permanent_error() -> None:
    with pytest.raises(PermanentEmbedError, match="expected 768, got 512"):
        check_dense_dimension([[0.0] * 512], 768)


def test_matching_dense_dimension_passes() -> None:
    check_dense_dimension([[0.0] * 768, [1.0] * 768], 768)
