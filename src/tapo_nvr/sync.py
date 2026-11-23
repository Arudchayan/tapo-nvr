"""Copy new camera SD-card recordings to a local or cloud-synced folder.

The camera records autonomously to its microSD card. This command pulls those
clips over the camera's local API and writes them to a directory, which can be
a Google Drive (or other cloud-synced) folder. It is the no-NVR-host
alternative to Frigate: the laptop only has to be awake long enough to copy new
clips, and the SD card buffers whatever it missed.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ConfigError, Settings
from .util import redact

DEFAULT_OUTPUT_DIR = Path("recordings")
DEFAULT_DAYS = 2

# An empty day may be reported as one of these playback errors instead of an
# empty list, depending on firmware.
_EMPTY_DAY_CODES = ("-40214", "-71112")

# The camera has no mounted SD card (or the card is unreadable).
_STORAGE_MISSING_CODES = ("-71114", "STORAGE_NOT_EXIST")


class SyncError(RuntimeError):
    """Raised when a single recording cannot be downloaded."""


@dataclass(frozen=True)
class Recording:
    """A recording window reported by the camera."""

    start: int
    end: int
    kind: str = ""

    @property
    def duration(self) -> int:
        """Length of the recording in seconds."""
        return self.end - self.start


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of one recording download."""

    path: Path
    skipped: bool = False
    in_progress: bool = False


def parse_date(value: str) -> date:
    """Parse a ``YYYY-MM-DD`` date."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ConfigError(f"Invalid date {value!r}; use YYYY-MM-DD.") from exc


def plan_dates(
    *,
    days: int,
    since: date | None,
    dates: Sequence[date],
    today: date | None = None,
) -> list[date]:
    """Return the dates to inspect, oldest first."""
    today = today or date.today()
    if dates:
        return sorted(set(dates))
    if days < 1:
        raise ConfigError("--days must be at least 1.")
    if since is not None:
        if since > today:
            raise ConfigError("--since cannot be in the future.")
        start = since
    else:
        start = today - timedelta(days=days - 1)
    return [start + timedelta(days=offset) for offset in range((today - start).days + 1)]


def flatten_recordings(payload: Iterable[object] | None) -> list[Recording]:
    """Flatten the camera's channel-wrapped recording list.

    Firmware returns entries shaped like
    ``{"search_video_results_1": {"startTime": ..., "endTime": ...}}``. A flat
    entry is accepted too, which keeps the parser tolerant of firmware changes.
    """
    by_window: dict[tuple[int, int], Recording] = {}
    for item in payload or ():
        if not isinstance(item, dict):
            continue
        flat = "startTime" in item or "start_time" in item
        values = (item,) if flat else item.values()
        for value in values:
            if not isinstance(value, dict):
                continue
            start = value.get("startTime", value.get("start_time"))
            end = value.get("endTime", value.get("end_time"))
            if start is None or end is None:
                continue
            try:
                start_epoch = int(start)
                end_epoch = int(end)
            except (TypeError, ValueError):
                continue
            if end_epoch <= start_epoch:
                continue
            kind = str(value.get("video_type", value.get("vedio_type", "")) or "")
            by_window[(start_epoch, end_epoch)] = Recording(start_epoch, end_epoch, kind)
    return [by_window[key] for key in sorted(by_window)]


def recording_filename(recording: Recording) -> str:
    """Return a stable, human-readable file name for a recording."""
    start = datetime.fromtimestamp(recording.start)
    end = datetime.fromtimestamp(recording.end)
    end_format = "%H%M%S" if end.date() == start.date() else "%Y%m%d-%H%M%S"
    return f"{start:%Y%m%d-%H%M%S}-{end.strftime(end_format)}.mp4"


def recording_path(output: Path, recording: Recording) -> Path:
    """Return the dated destination path for a recording."""
    start = datetime.fromtimestamp(recording.start)
    return output / start.strftime("%Y-%m-%d") / recording_filename(recording)


def _load_camera(settings: Settings) -> Any:
    if sys.version_info < (3, 11):  # pragma: no cover - depends on the interpreter
        raise ConfigError(
            "The sync command requires Python 3.11 or newer because its pytapo "
            "dependency uses asyncio.timeout. The relay and Frigate commands still "
            "work on Python 3.10."
        )
    try:
        from pytapo import Tapo
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ConfigError(
            "The sync command needs the optional 'pytapo' dependency. "
            "Install it with: pip install 'tapo-nvr[sync]'"
        ) from exc

    # SD-card playback always authenticates the media stream with the Tapo
    # cloud password. Newer firmware also uses it for the control API.
    return Tapo(
        settings.camera_host,
        "admin",
        settings.camera_cloud_password,
        cloudPassword=settings.camera_cloud_password,
        printDebugInformation=False,
    )


def _downloader_class() -> type:
    try:
        from pytapo.media_stream.downloader import Downloader
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ConfigError(
            "The sync command needs the optional 'pytapo' dependency. "
            "Install it with: pip install 'tapo-nvr[sync]'"
        ) from exc
    return Downloader


def _require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise ConfigError(
            f"Missing required executable(s): {', '.join(missing)}. Install FFmpeg "
            "(with both ffmpeg and ffprobe) and make sure it is on PATH."
        )


def _is_empty_day(exc: Exception) -> bool:
    message = str(exc)
    return any(code in message for code in _EMPTY_DAY_CODES)


def _is_storage_missing(exc: Exception) -> bool:
    message = str(exc)
    return any(code in message for code in _STORAGE_MISSING_CODES)


def _describe_dates(planned: Sequence[date]) -> str:
    if len(planned) == 1:
        return planned[0].isoformat()
    contiguous = all(
        (planned[index] - planned[index - 1]).days == 1 for index in range(1, len(planned))
    )
    if contiguous:
        return f"{planned[0].isoformat()} to {planned[-1].isoformat()}"
    return ", ".join(day.isoformat() for day in planned)


async def _download_one(
    tapo: Any,
    recording: Recording,
    time_correction: int,
    target: Path,
    *,
    overwrite: bool,
) -> DownloadResult:
    if target.is_file() and target.stat().st_size > 0 and not overwrite:
        return DownloadResult(target, skipped=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = tempfile.mkdtemp(prefix="tapo-nvr-sync-")
    partial = target.with_name(target.name + ".part")
    downloader = _downloader_class()(
        tapo,
        recording.start,
        recording.end,
        time_correction,
        staging,
        fileName=target.name,
        output="mp4",
        method="download",
        progressInterval=5.0,
    )
    progress_started = False
    try:
        last_action = ""
        async for status in downloader.download():
            action = str(status.get("currentAction") or "")
            if action == "Recording in progress":
                return DownloadResult(target, skipped=True, in_progress=True)
            if action == "Camera busy":
                raise SyncError(f"the camera is busy (error {status.get('errorCode')})")
            if action == "Giving up":
                raise SyncError("the camera stopped sending data before the clip finished")
            if action == "Skipping":
                raise SyncError("the downloader skipped the file unexpectedly")
            if action and action != last_action:
                print(f"    {action.lower()}...", end="", flush=True)
                progress_started = True
                last_action = action
        staged = Path(staging) / target.name
        if not staged.is_file() or staged.stat().st_size == 0:
            raise SyncError("no video data was written")
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
        try:
            os.replace(staged, partial)
        except OSError:
            # The staging directory and the output folder can be on different
            # filesystems (for example a local temp disk and a Google Drive
            # mount). Fall back to a plain copy.
            shutil.copyfile(staged, partial)
            staged.unlink()
        os.replace(partial, target)
        return DownloadResult(target)
    finally:
        if progress_started:
            print()
        shutil.rmtree(staging, ignore_errors=True)
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()


async def _sync_async(
    tapo: Any,
    destination: Path,
    planned: Sequence[date],
    *,
    dry_run: bool,
    overwrite: bool,
) -> tuple[int, int, int]:
    try:
        time_correction = await asyncio.to_thread(tapo.getTimeCorrection)
    except Exception as exc:
        print(f"  warning: could not get the camera time correction: {redact(str(exc))}")
        time_correction = 0
    downloaded = skipped = failed = 0

    for day in planned:
        print(f"Checking {day.isoformat()}...")
        try:
            payload = await asyncio.to_thread(tapo.getRecordings, day.strftime("%Y%m%d"))
        except Exception as exc:
            if _is_storage_missing(exc):
                raise ConfigError(
                    "The camera reports no SD-card storage. Insert a microSD card, "
                    "format it in the Tapo app, and enable Storage & Recording > "
                    "Local Recording."
                ) from exc
            if _is_empty_day(exc):
                print("  no recordings")
                continue
            print(f"  error: {redact(str(exc))}")
            failed += 1
            continue

        recordings = flatten_recordings(payload)
        if not recordings:
            print("  no recordings")
            continue

        print(f"  {len(recordings)} recording(s)")
        for recording in recordings:
            try:
                target = recording_path(destination, recording)
            except (OSError, ValueError, OverflowError) as exc:
                print(f"  error: invalid recording timestamp: {redact(str(exc))}")
                failed += 1
                continue
            if dry_run:
                state = "would overwrite" if target.exists() else "would download"
                print(f"  {state} {target} ({recording.duration}s)")
                continue
            try:
                result = await _download_one(
                    tapo,
                    recording,
                    time_correction,
                    target,
                    overwrite=overwrite,
                )
            except Exception as exc:
                print(f"  error {target.name}: {redact(str(exc))}")
                failed += 1
                continue
            if result.in_progress:
                print(f"  skipped {target.name} (still recording)")
                skipped += 1
            elif result.skipped:
                print(f"  skipped {target.name} (already downloaded)")
                skipped += 1
            else:
                print(f"  saved {target}")
                downloaded += 1

    return downloaded, skipped, failed


def run_sync(
    settings: Settings,
    *,
    output: Path | None = None,
    days: int = DEFAULT_DAYS,
    since: str | None = None,
    dates: Sequence[str] = (),
    dry_run: bool = False,
    overwrite: bool = False,
) -> int:
    """Download new SD-card recordings and return a process exit code."""
    settings.require_sync()
    destination = (output or Path(settings.sync_output_dir or DEFAULT_OUTPUT_DIR)).expanduser()
    since_date = parse_date(since) if since else None
    explicit_dates = tuple(parse_date(value) for value in dates)
    planned = plan_dates(days=days, since=since_date, dates=explicit_dates)

    if not dry_run:
        _require_ffmpeg()
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(
                f"Could not create the output directory {destination}: {exc}"
            ) from exc

    print(f"Camera: {settings.camera_host}")
    print(f"Output: {destination}")
    print(f"Dates:  {_describe_dates(planned)}")
    if dry_run:
        print("Dry run: nothing will be downloaded.")

    try:
        tapo = _load_camera(settings)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(
            f"Could not connect to the camera at {settings.camera_host}: {redact(str(exc))}"
        ) from exc

    try:
        downloaded, skipped, failed = asyncio.run(
            _sync_async(
                tapo,
                destination,
                planned,
                dry_run=dry_run,
                overwrite=overwrite,
            )
        )
    finally:
        with contextlib.suppress(Exception):
            tapo.close()

    print()
    print(f"Done: {downloaded} downloaded, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0
