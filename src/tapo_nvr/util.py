"""Small shared helpers."""

from __future__ import annotations

import re

_URL_CREDENTIALS = re.compile(r"(?i)\b((?:rtsps?|https?)://)[^\s]*@")
_ENV_SECRETS = re.compile(
    r"(?i)\b(FRIGATE_CAMERA_PASSWORD|FRIGATE_TAPO_PASSWORD|CAMERA_PASSWORD"
    r"|NVR_SSH_PASSWORD|PASSWORD)(\s*[=:]\s*)(\S+)"
)


def redact(text: str) -> str:
    """Replace likely credentials in ``text`` with ``***``.

    Handles RTSP/HTTP URLs (including passwords containing ``@`` or ``/``)
    and ``PASSWORD=value`` style pairs in captured logs.
    """
    text = _URL_CREDENTIALS.sub(r"\1***@", text)
    return _ENV_SECRETS.sub(r"\1\2***", text)
