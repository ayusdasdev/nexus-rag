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
        (b"\xef\xbb\xbf<!DOCTYPE html><html></html>", "text/html"),
        (b"\xef\xbb\xbf  <html>", "text/html"),
        (b"  \n\t<!doctype html>", "text/html"),
        (b"<head><title>x</title></head>", "text/html"),
        (b"  <head>\n<meta charset=utf-8>", "text/html"),
        (b"<body><p>hi</p></body>", "text/html"),
        (b"<headline>not html", "text/plain"),
        (b"\xef\xbb\xbf# Markdown with a BOM", "text/plain"),
        (b"", None),
        (b"\x89PNG\r\n\x1a\n", None),
        (b"abc\x00def", None),
        (b"\xff\xfe", None),
    ],
)
def test_detect_content_type_by_content(data: bytes, expected: str | None) -> None:
    assert detect_content_type(data) == expected
