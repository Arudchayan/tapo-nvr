"""Tests for continuous laptop recording helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from tapo_nvr import record
from tapo_nvr.config import ConfigError, Settings


def make_settings(**overrides) -> Settings:
    values = {
        "camera_host": "camera.local",
        "camera_username": "arudchayan01@gmail.com",
        "camera_password": "p@ss:/",
        "camera_record_stream": "stream1",
    }
    values.update(overrides)
    return Settings(**values)


def test_build_rtsp_url_escapes_credentials() -> None:
    url = record.build_rtsp_url(make_settings())

    assert url == ("rtsp://arudchayan01%40gmail.com:p%40ss%3A%2F@camera.local:554/stream1")


def test_build_ffmpeg_command_uses_segments_and_stream_copy(tmp_path: Path) -> None:
    command = record.build_ffmpeg_command(make_settings(), tmp_path, 1800)

    assert command[0] == "ffmpeg"
    assert "-rtsp_transport" in command
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-segment_time") + 1] == "1800"
    assert command[command.index("-segment_atclocktime") + 1] == "1"
    assert command[command.index("-timeout") + 1] == "15000000"
    assert command[command.index("-segment_list") + 1] == str(tmp_path / record.SEGMENT_LIST_NAME)
    assert command[command.index("-strftime") + 1] == "1"
    assert command[-1] == str(tmp_path / "%Y%m%d_%H%M%S.mp4")


def test_closed_segments_reads_the_ffmpeg_list(tmp_path: Path) -> None:
    clip = tmp_path / "20260101_000000.mp4"
    clip.write_bytes(b"clip")
    missing = tmp_path / "20260101_010000.mp4"
    (tmp_path / record.SEGMENT_LIST_NAME).write_text(
        f'"{clip.name}"\n{missing.name}\nmanual.mp4\n', encoding="utf-8"
    )

    assert record.closed_segments(tmp_path) == [clip]


def test_acquire_lock_blocks_a_second_instance(tmp_path: Path) -> None:
    lock = record.acquire_lock(tmp_path)

    with pytest.raises(ConfigError):
        record.acquire_lock(tmp_path)

    lock.unlink()


def test_stop_process_uses_a_windows_process_tree(monkeypatch) -> None:
    calls = []

    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_run(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(record.os, "name", "nt")
    monkeypatch.setattr(record.subprocess, "run", fake_run)

    record._stop_process(FakeProcess())

    assert calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]


def test_acquire_lock_replaces_a_stale_lock(tmp_path: Path) -> None:
    (tmp_path / record.LOCK_NAME).write_text("999999", encoding="utf-8")

    lock = record.acquire_lock(tmp_path)

    assert lock.read_text(encoding="utf-8") == str(os.getpid())
    lock.unlink()


def test_status_writes_json_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    status = record.Status(path, make_settings(), tmp_path / "staging", tmp_path / "out")

    status.update(state="recording", published_total=2)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["state"] == "recording"
    assert data["published_total"] == 2
    assert data["pid"] == os.getpid()


def test_newest_segment_finds_the_active_file(tmp_path: Path) -> None:
    clip = tmp_path / "20260101_000000.mp4"
    clip.write_bytes(b"clip")

    assert record._newest_segment(tmp_path) == clip


def test_output_requires_a_sentinel(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        record._check_output(tmp_path)

    (tmp_path / record.OUTPUT_SENTINEL_NAME).write_text("", encoding="utf-8")
    record._check_output(tmp_path)


def test_run_record_rejects_overlapping_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(record, "_require_ffmpeg", lambda: None)

    with pytest.raises(ConfigError):
        record.run_record(
            make_settings(),
            output=tmp_path,
            staging=tmp_path,
            check=True,
        )


def test_parse_segment_start() -> None:
    assert record.parse_segment_start(Path("20261123_143000.mp4")) == datetime(2026, 11, 23, 14, 30)
    assert record.parse_segment_start(Path("not-a-segment.mp4")) is None
    assert record.parse_segment_start(Path("20261323_143000.mp4")) is None


def test_segment_destination_uses_the_start_date(tmp_path: Path) -> None:
    source = tmp_path / "20261123_143000.mp4"

    assert record.segment_destination(tmp_path / "out", source) == (
        tmp_path / "out" / "2026-11-23" / "20261123_143000.mp4"
    )


def test_publish_segment_copies_once(tmp_path: Path) -> None:
    source = tmp_path / "staging" / "20261123_143000.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    destination = tmp_path / "out" / "2026-11-23" / source.name

    assert record.publish_segment(source, destination) is True
    assert destination.read_bytes() == b"video"

    mtime = destination.stat().st_mtime_ns
    assert record.publish_segment(source, destination) is False
    assert destination.stat().st_mtime_ns == mtime


def test_pending_segments_only_returns_closed_files(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    old = tmp_path / "20260101_000000.mp4"
    recent = tmp_path / "20260101_000100.mp4"
    old.write_bytes(b"old")
    recent.write_bytes(b"recent")
    os.utime(old, (now - 600, now - 600))
    os.utime(recent, (now - 30, now - 30))
    (tmp_path / record.SEGMENT_LIST_NAME).write_text(
        f"{old.name}\n{recent.name}\n", encoding="utf-8"
    )

    assert record.pending_segments(tmp_path, min_age_seconds=120, now=now) == [old]


def test_cleanup_output_removes_only_old_dated_files(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    output = tmp_path / "out"

    old_folder = output / "2026-11-01"
    old_folder.mkdir(parents=True)
    old = old_folder / "20261101_120000.mp4"
    old.write_bytes(b"old")
    os.utime(old, (now - 8 * 86400, now - 8 * 86400))

    recent_folder = output / "2026-11-23"
    recent_folder.mkdir(parents=True)
    recent = recent_folder / "20261123_120000.mp4"
    recent.write_bytes(b"recent")
    os.utime(recent, (now - 3600, now - 3600))

    unrelated = output / "notes"
    unrelated.mkdir()
    keep = unrelated / "keep.mp4"
    keep.write_bytes(b"keep")
    os.utime(keep, (now - 8 * 86400, now - 8 * 86400))

    loose = output / "loose.mp4"
    loose.write_bytes(b"loose")
    os.utime(loose, (now - 8 * 86400, now - 8 * 86400))

    sync_clip = old_folder / "20261101-120000-120500.mp4"
    sync_clip.write_bytes(b"sync")
    os.utime(sync_clip, (now - 8 * 86400, now - 8 * 86400))

    removed = record.cleanup_output(output, keep_days=7, now=now)

    assert removed == 1
    assert not old.exists()
    assert sync_clip.exists()
    assert old_folder.exists()  # the sync clip keeps the date folder
    assert recent.exists()
    assert keep.exists()
    assert loose.exists()


def test_cleanup_output_zero_keeps_everything(tmp_path: Path) -> None:
    output = tmp_path / "out" / "2026-11-01"
    output.mkdir(parents=True)
    old = output / "old.mp4"
    old.write_bytes(b"old")
    os.utime(old, (0, 0))

    assert record.cleanup_output(tmp_path / "out", keep_days=0) == 0
    assert old.exists()


def test_cleanup_removes_only_published_old_segments(tmp_path: Path) -> None:
    now = 1_800_000_000.0
    staging = tmp_path / "staging"
    output = tmp_path / "out"
    staging.mkdir()

    published = staging / "20260101_000000.mp4"
    published.write_bytes(b"published")
    record.publish_segment(published, record.segment_destination(output, published))
    os.utime(published, (now - 7200, now - 7200))

    recent = staging / "20260101_000100.mp4"
    recent.write_bytes(b"recent")
    record.publish_segment(recent, record.segment_destination(output, recent))
    os.utime(recent, (now - 60, now - 60))

    unpublished = staging / "20260101_000200.mp4"
    unpublished.write_bytes(b"unpublished")
    os.utime(unpublished, (now - 7200, now - 7200))
    (staging / record.SEGMENT_LIST_NAME).write_text(
        f"{published.name}\n{recent.name}\n{unpublished.name}\n", encoding="utf-8"
    )

    removed = record.cleanup_published(staging, output, keep_hours=1, now=now)

    assert removed == 1
    assert not published.exists()
    assert recent.exists()
    assert unpublished.exists()


def test_run_record_requires_camera_credentials(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        record.run_record(
            Settings(camera_host="camera.local"),
            output=tmp_path / "out",
            staging=tmp_path / "staging",
            check=True,
        )

    message = str(excinfo.value)
    assert "CAMERA_USERNAME" in message
    assert "CAMERA_PASSWORD" in message
