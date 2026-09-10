"""Tests for shared helpers."""

from __future__ import annotations

from tapo_nvr.util import redact


def test_redact_hides_rtsp_credentials() -> None:
    text = "rtsp://cam:secret@100.64.0.1:8554/stream1 failed"
    result = redact(text)

    assert "secret" not in result
    assert result == "rtsp://***@100.64.0.1:8554/stream1 failed"


def test_redact_leaves_other_urls_alone() -> None:
    text = "http://example.com/health"
    assert redact(text) == text
