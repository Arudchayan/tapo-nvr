"""Tests for shared helpers."""

from __future__ import annotations

from tapo_nvr.util import redact


def test_redact_hides_rtsp_credentials() -> None:
    text = "rtsp://cam:secret@100.64.0.1:8554/stream1 failed"

    assert redact(text) == "rtsp://***@100.64.0.1:8554/stream1 failed"


def test_redact_handles_special_characters_in_passwords() -> None:
    text = "rtsp://camera-user:p@ss:w/rd@100.64.0.1:8554/stream1"

    result = redact(text)

    assert "p@ss" not in result
    assert "w/rd" not in result
    assert result.startswith("rtsp://***@")


def test_redact_handles_password_assignments() -> None:
    result = redact("FRIGATE_CAMERA_PASSWORD=p%40ss\n")

    assert result == "FRIGATE_CAMERA_PASSWORD=***\n"


def test_redact_leaves_other_urls_alone() -> None:
    text = "http://example.com/health"
    assert redact(text) == text
