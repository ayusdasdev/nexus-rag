import re

_PDF_MAGIC = b"%PDF-"
_HTML_OPENING_TAG = re.compile(r"<(!doctype html|html|head|body)[\s>]")
_SNIFF_CHARS = 512


def detect_content_type(data: bytes) -> str | None:
    """Classify by content, never by client-supplied type or filename.

    Returns None when the bytes are not an accepted type.
    """
    if not data:
        return None
    if data.startswith(_PDF_MAGIC):
        return "application/pdf"
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if _HTML_OPENING_TAG.match(text[:_SNIFF_CHARS].lstrip().lower()):
        return "text/html"
    return "text/plain"
