"""Tests for SD-card recording sync."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path

import pytest

from tapo_nvr import sync
from tapo_nvr.config import ConfigError, Settings


class FakeCamera:
    """Minimal stand-in for ``pytapo.Tapo``."""

    def __init__(self, recordings: list[object] | None = None) -> None:
        self.recordings = recordings if recordings is not None else []
        self.closed = False

    def getTimeCorrection(self) -> int:
        return 0

    def getRecordings(self, date: str) -> list[object]:
        return self.recordings

    def close(self) -> None:
        self.closed = True


def test_flatten_recordings_unwraps_numbered_entries() -> None:
    payload = [
        {"search_video_results_2": {"startTime": 200, "endTime": 260, "vedio_type": "2"}},
        {"search_video_results_1": {"startTime": 100, "endTime": 160, "video_type": "1"}},
    ]

    recordings = sync.flatten_recordings(payload)

    assert [(item.start, item.end, item.kind) for item in recordings] == [
        (100, 160, "1"),
        (200, 260, "2"),
    ]


def test_flatten_recordings_accepts_flat_entries_and_ignores_invalid() -> None:
    payload = [
        {"startTime": "100", "endTime": "160"},
        {"start_time": 10, "end_time": 20},
        {"startTime": 5, "endTime": 5},
        {"startTime": "not-a-number", "endTime": 20},
        "junk",
    ]

    recordings = sync.flatten_recordings(payload)

    assert [(item.start, item.end) for item in recordings] == [(10, 20), (100, 160)]


def test_recording_filename_and_path_are_stable() -> None:
    recording = sync.Recording(
        start=int(datetime(2026, 11, 22, 14, 30, 0).timestamp()),
        end=int(datetime(2026, 11, 22, 14, 32, 45).timestamp()),
    )

    assert sync.recording_filename(recording) == "20261122-143000-143245.mp4"
    assert sync.recording_path(Path("out"), recording) == Path(
        "out/2026-11-22/20261122-143000-143245.mp4"
    )


def test_recording_filename_includes_the_end_date_across_midnight() -> None:
    recording = sync.Recording(
        start=int(datetime(2026, 11, 22, 23, 50, 0).timestamp()),
        end=int(datetime(2026, 11, 23, 0, 10, 0).timestamp()),
    )

    assert sync.recording_filename(recording) == "20261122-235000-20261123-001000.mp4"


def test_plan_dates_uses_a_rolling_window() -> None:
    today = date(2026, 11, 22)

    assert sync.plan_dates(days=1, since=None, dates=(), today=today) == [today]
    assert sync.plan_dates(days=3, since=None, dates=(), today=today) == [
        date(2026, 11, 20),
        date(2026, 11, 21),
        today,
    ]


def test_plan_dates_handles_since_and_explicit_dates() -> None:
    today = date(2026, 11, 22)

    assert sync.plan_dates(days=1, since=date(2026, 11, 20), dates=(), today=today) == [
        date(2026, 11, 20),
        date(2026, 11, 21),
        today,
    ]
    assert sync.plan_dates(
        days=1,
        since=None,
        dates=[today, date(2026, 11, 20), today],
        today=today,
    ) == [date(2026, 11, 20), today]


def test_plan_dates_rejects_invalid_ranges() -> None:
    today = date(2026, 11, 22)

    with pytest.raises(ConfigError):
        sync.plan_dates(days=0, since=None, dates=(), today=today)
    with pytest.raises(ConfigError):
        sync.plan_dates(days=1, since=date(2026, 11, 23), dates=(), today=today)


def test_parse_date_rejects_other_formats() -> None:
    assert sync.parse_date("2026-11-22") == date(2026, 11, 22)
    with pytest.raises(ConfigError):
        sync.parse_date("22/11/2026")


def test_describe_dates() -> None:
    assert sync._describe_dates([date(2026, 11, 22)]) == "2026-11-22"
    assert sync._describe_dates([date(2026, 11, 21), date(2026, 11, 22)]) == (
        "2026-11-21 to 2026-11-22"
    )
    assert sync._describe_dates([date(2026, 11, 1), date(2026, 11, 20)]) == (
        "2026-11-01, 2026-11-20"
    )


def test_run_sync_dry_run_does_not_write(tmp_path: Path, monkeypatch, capsys) -> None:
    fake = FakeCamera(
        [{"search_video_results_1": {"startTime": 100, "endTime": 160, "vedio_type": "2"}}]
    )
    monkeypatch.setattr(sync, "_load_camera", lambda settings: fake)
    settings = Settings(camera_host="camera.local", camera_cloud_password="cloud")

    code = sync.run_sync(settings, output=tmp_path, days=1, dry_run=True)

    output = capsys.readouterr().out
    assert code == 0
    assert "would download" in output
    assert list(tmp_path.iterdir()) == []
    assert fake.closed is True


def test_run_sync_treats_empty_day_error_as_no_recordings(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    class EmptyCamera(FakeCamera):
        def getRecordings(self, date: str) -> list[object]:
            raise RuntimeError("-40214 no video")

    fake = EmptyCamera()
    monkeypatch.setattr(sync, "_load_camera", lambda settings: fake)
    settings = Settings(camera_host="camera.local", camera_cloud_password="cloud")

    code = sync.run_sync(settings, output=tmp_path, days=1, dry_run=True)

    assert code == 0
    assert "no recordings" in capsys.readouterr().out


def test_run_sync_reports_missing_storage(tmp_path: Path, monkeypatch) -> None:
    class NoStorageCamera(FakeCamera):
        def getRecordings(self, date: str) -> list[object]:
            raise RuntimeError("-71114 STORAGE_NOT_EXIST")

    fake = NoStorageCamera()
    monkeypatch.setattr(sync, "_load_camera", lambda settings: fake)
    settings = Settings(camera_host="camera.local", camera_cloud_password="cloud")

    with pytest.raises(ConfigError) as excinfo:
        sync.run_sync(settings, output=tmp_path, days=1, dry_run=True)

    assert "SD-card storage" in str(excinfo.value)
    assert fake.closed is True


def test_run_sync_requires_camera_and_cloud_password(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        sync.run_sync(Settings(), output=tmp_path, days=1, dry_run=True)

    message = str(excinfo.value)
    assert "CAMERA_HOST" in message
    assert "CAMERA_CLOUD_PASSWORD" in message


def test_run_sync_downloads_and_reports_failures(tmp_path: Path, monkeypatch, capsys) -> None:
    recordings = [
        {"search_video_results_1": {"startTime": 100, "endTime": 160}},
        {"search_video_results_2": {"startTime": 200, "endTime": 260}},
    ]
    fake = FakeCamera(recordings)
    monkeypatch.setattr(sync, "_load_camera", lambda settings: fake)
    monkeypatch.setattr(sync, "_require_ffmpeg", lambda: None)

    async def fake_download(tapo, recording, correction, target, *, overwrite):
        if recording.start == 200:
            raise sync.SyncError("simulated failure")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"video")
        return sync.DownloadResult(target)

    monkeypatch.setattr(sync, "_download_one", fake_download)
    settings = Settings(camera_host="camera.local", camera_cloud_password="cloud")

    code = sync.run_sync(settings, output=tmp_path, days=1)

    output = capsys.readouterr().out
    assert code == 1
    assert "1 downloaded, 0 skipped, 1 failed" in output
    assert len(list(tmp_path.rglob("*.mp4"))) == 1


class FakeDownloader:
    """Write a file into the staging directory, like pytapo's downloader."""

    def __init__(self, *args, **kwargs) -> None:
        self.outputDirectory = args[4]
        self.fileName = kwargs["fileName"]

    async def download(self):
        path = Path(self.outputDirectory) / self.fileName
        path.write_bytes(b"video")
        yield {"currentAction": "Downloading", "progress": 0, "total": 60}
        yield {"currentAction": "Converting", "progress": 0, "total": 0}


def test_download_one_writes_through_staging(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sync, "_downloader_class", lambda: FakeDownloader)
    recording = sync.Recording(start=100, end=160)
    target = sync.recording_path(tmp_path, recording)

    result = asyncio.run(sync._download_one(FakeCamera(), recording, 0, target, overwrite=False))

    assert result.skipped is False
    assert target.read_bytes() == b"video"


def test_download_one_skips_existing_without_calling_the_downloader(
    tmp_path: Path, monkeypatch
) -> None:
    def fail() -> type:
        raise AssertionError("downloader must not be constructed")

    monkeypatch.setattr(sync, "_downloader_class", fail)
    recording = sync.Recording(start=100, end=160)
    target = sync.recording_path(tmp_path, recording)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")

    result = asyncio.run(sync._download_one(FakeCamera(), recording, 0, target, overwrite=False))

    assert result.skipped is True
    assert target.read_bytes() == b"old"


def test_download_one_overwrites_when_requested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sync, "_downloader_class", lambda: FakeDownloader)
    recording = sync.Recording(start=100, end=160)
    target = sync.recording_path(tmp_path, recording)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")

    asyncio.run(sync._download_one(FakeCamera(), recording, 0, target, overwrite=True))

    assert target.read_bytes() == b"video"


def test_download_one_marks_a_recording_in_progress(tmp_path: Path, monkeypatch) -> None:
    class InProgressDownloader:
        def __init__(self, *args, **kwargs) -> None:
            self.outputDirectory = args[4]

        async def download(self):
            yield {"currentAction": "Recording in progress"}

    monkeypatch.setattr(sync, "_downloader_class", lambda: InProgressDownloader)
    recording = sync.Recording(start=100, end=160)
    target = sync.recording_path(tmp_path, recording)

    result = asyncio.run(sync._download_one(FakeCamera(), recording, 0, target, overwrite=False))

    assert result.in_progress is True
    assert not target.exists()
