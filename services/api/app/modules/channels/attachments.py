"""Filename and MIME rules for conversation attachments.

A customer-supplied filename is display-only: it never becomes a path segment.
The stored object key is always generated from the message id (inbound) or a
UUID (outbound), with a suffix derived from the name only when it is a short,
safe token. This keeps a crafted filename from escaping the private store while
still showing the customer's real name in the inbox.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

# Common document/image types get a stable suffix even when the customer's
# filename has none (Meta sometimes omits it on forwarded media).
EXTENSIONS_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

_SAFE_SUFFIX = re.compile(r"^[A-Za-z0-9]{1,8}$")


def storage_suffix(mime: str, original: str | None) -> str:
    """A safe suffix for a generated storage key."""
    suffix = Path(original or "").suffix.lstrip(".")
    if suffix and _SAFE_SUFFIX.match(suffix):
        return f".{suffix.lower()}"
    return EXTENSIONS_BY_MIME.get(mime, ".bin")


def display_name(original: str | None, suffix: str) -> str:
    """Customer-facing filename: basename only, printable, bounded."""
    name = Path(str(original or "").replace("\\", "/")).name.strip()
    name = "".join(ch for ch in name if ch.isprintable())[:200]
    return name or f"attachment{suffix}"


def normalize_mime(mime: str | None, filename: str | None) -> str:
    """The MIME type to store and send, with a filename-derived fallback."""
    value = (mime or "").split(";")[0].strip().lower()
    if value and value != "application/octet-stream":
        return value[:100]
    guessed, _ = mimetypes.guess_type(filename or "")
    return (guessed or "application/octet-stream")[:100]
