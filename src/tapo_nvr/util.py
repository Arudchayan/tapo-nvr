"""Small shared helpers."""

from __future__ import annotations

import re

_RTSP_CREDENTIALS = re.compile(r"(?i)\b(rtsp://)[^@\s/]+@")


def redact(text: str) -> str:
    """Replace credentials embedded in RTSP URLs with ``***``."""
    return _RTSP_CREDENTIALS.sub(r"\1***@", text)
