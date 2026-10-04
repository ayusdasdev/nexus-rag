_PDF_MAGIC = b"%PDF-"
_HTML_PREFIXES = (b"<!doctype html", b"<html")
_SNIFF_BYTES = 512


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
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    head = text[:_SNIFF_BYTES].lstrip().lower().encode("utf-8")
    if head.startswith(_HTML_PREFIXES):
        return "text/html"
    return "text/plain"
