import pytest

from app.services.file_validation import detect_content_type


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"%PDF-1.7\n%rest of pdf", "application/pdf"),
        (b"<!DOCTYPE html><html></html>", "text/html"),
        (b"<html><body>hi</body></html>", "text/html"),
        (b"# Title\n\nbody text", "text/plain"),
        (b"plain text", "text/plain"),
        (b"%PDF", "text/plain"),
        (b"", None),
        (b"\x89PNG\r\n\x1a\n", None),
        (b"abc\x00def", None),
        (b"\xff\xfe", None),
    ],
)
def test_detect_content_type_by_content(data: bytes, expected: str | None) -> None:
    assert detect_content_type(data) == expected
