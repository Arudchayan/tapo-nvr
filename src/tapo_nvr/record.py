"""Record the camera's RTSP stream continuously to a publish folder.

ffmpeg writes clock-aligned MP4 segments into a local staging directory and
records every closed segment in a segment list. The publisher copies listed
segments into the output directory and keeps the local copy for a grace period.
A status heartbeat and a rotating log make headless failures visible.
"""

from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .config import ConfigError, Settings
from .util import redact

FILE_RE = re.compile(r"^(\d{8})_(\d{6})\.mp4$")
SEGMENT_LIST_NAME = "segments.csv"
LOCK_NAME = ".tapo-nvr.lock"
STATUS_NAME = "status.json"
LOG_NAME = "record.log"
OUTPUT_SENTINEL_NAME = ".tapo-nvr-output"
DEFAULT_MIN_FREE_GB = 10
DEFAULT_STALL_SECONDS = 300
MIN_PUBLISH_AGE_SECONDS = 2
PUBLISH_INTERVAL_SECONDS = 30
FFMPEG_STOP_TIMEOUT_SECONDS = 15
MAX_BACKOFF_SECONDS = 300

LOGGER = logging.getLogger("tapo_nvr.record")


def _log(message: str) -> None:
    LOGGER.info(message)


def _warn(message: str) -> None:
    LOGGER.warning(message)


def _error(message: str) -> None:
    LOGGER.error(message)


def configure_logging(log_file: Path | None) -> None:
    """Install a console and rotating file log handler."""
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        LOGGER.addHandler(stream)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError as exc:
            raise ConfigError(f"Cannot open the recorder log {log_file}: {exc}") from exc
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mtime(path: Path, default: float) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return default


def build_rtsp_url(settings: Settings) -> str:
    """Build an RTSP URL with URL-encoded credentials."""
    user = quote(settings.camera_username, safe="")
    password = quote(settings.camera_password, safe="")
    return (
        f"rtsp://{user}:{password}@{settings.camera_host}:"
        f"{settings.camera_rtsp_port}/{settings.camera_record_stream}"
    )


def build_ffmpeg_command(
    settings: Settings,
    staging: Path,
    segment_seconds: int,
) -> list[str]:
    """Build the ffmpeg command used by the recorder."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-use_wallclock_as_timestamps",
        "1",
        "-fflags",
        "+genpts",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "15000000",
        "-i",
        build_rtsp_url(settings),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-segment_atclocktime",
        "1",
        "-reset_timestamps",
        "1",
        "-segment_list",
        str(staging / SEGMENT_LIST_NAME),
        "-segment_list_type",
        "csv",
        "-segment_format",
        "mp4",
        "-segment_format_options",
        "movflags=+frag_keyframe+empty_moov+default_base_moof",
        "-strftime",
        "1",
        str(staging / "%Y%m%d_%H%M%S.mp4"),
    ]


def parse_segment_start(path: Path) -> datetime | None:
    """Return the segment start time encoded in its file name."""
    match = FILE_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def segment_destination(output: Path, source: Path) -> Path:
    """Return the dated publish path for a staging segment."""
    start = parse_segment_start(source)
    day = start or datetime.fromtimestamp(_mtime(source, time.time()))
    return output / day.strftime("%Y-%m-%d") / source.name


def _segment_list(staging: Path) -> Path:
    return staging / SEGMENT_LIST_NAME


def closed_segments(staging: Path) -> list[Path]:
    """Return segments that ffmpeg has written to its closed-segment list."""
    list_path = _segment_list(staging)
    if not list_path.is_file():
        return []
    paths: list[Path] = []
    try:
        lines = list_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        name = line.split(",", 1)[0].strip().strip('"')
        if not name:
            continue
        path = Path(name)
        if not path.is_absolute():
            path = staging / path
        try:
            if path.is_file() and path.stat().st_size > 0 and FILE_RE.match(path.name):
                paths.append(path)
        except OSError:
            continue
    return sorted(set(paths), key=lambda path: _mtime(path, 0.0))


def validate_segment(path: Path) -> bool:
    """Return True when ffprobe can read a positive duration from a segment."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        return float(result.stdout.strip()) > 0
    except ValueError:
        return False


def publish_segment(source: Path, destination: Path) -> bool:
    """Copy one validated segment to its publish path; return False if already there."""
    source_size = source.stat().st_size
    if destination.is_file() and destination.stat().st_size == source_size:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, destination)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
    return True


def pending_segments(
    staging: Path,
    *,
    min_age_seconds: int = MIN_PUBLISH_AGE_SECONDS,
    now: float | None = None,
) -> list[Path]:
    """Return closed, stable segments that are ready to publish."""
    current = time.time() if now is None else now
    found = []
    for path in closed_segments(staging):
        try:
            if current - path.stat().st_mtime >= min_age_seconds:
                found.append(path)
        except OSError:
            continue
    return found


def publish_pending(
    staging: Path,
    output: Path,
    *,
    min_age_seconds: int = MIN_PUBLISH_AGE_SECONDS,
) -> tuple[int, int]:
    """Publish all ready segments; return (published, failed)."""
    published = failed = 0
    for source in pending_segments(staging, min_age_seconds=min_age_seconds):
        if not validate_segment(source):
            _warn(f"skipping invalid segment {source.name}")
            failed += 1
            continue
        try:
            destination = segment_destination(output, source)
            if publish_segment(source, destination):
                _log(f"published {source.name} -> {destination}")
                published += 1
        except OSError as exc:
            _error(f"could not publish {source.name}: {exc}")
            failed += 1
    return published, failed


def cleanup_published(
    staging: Path,
    output: Path,
    keep_hours: int,
    *,
    now: float | None = None,
) -> int:
    """Delete local segments that are closed, published, and older than the grace period."""
    current = time.time() if now is None else now
    removed = 0
    for source in closed_segments(staging):
        try:
            destination = segment_destination(output, source)
            if not destination.is_file():
                continue
            if destination.stat().st_size != source.stat().st_size:
                continue
            if keep_hours > 0 and current - source.stat().st_mtime < keep_hours * 3600:
                continue
            source.unlink()
            removed += 1
        except OSError as exc:
            _warn(f"could not remove {source.name}: {exc}")
    if removed:
        _log(f"removed {removed} published segment(s) from {staging}")
    return removed


def cleanup_output(
    output: Path,
    keep_days: int,
    *,
    now: float | None = None,
) -> int:
    """Delete published files older than ``keep_days`` from dated output folders."""
    if keep_days <= 0 or not output.is_dir():
        return 0
    current = time.time() if now is None else now
    cutoff = current - keep_days * 86400
    removed = 0
    for folder in output.iterdir():
        try:
            if not folder.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder.name):
                continue
            for path in folder.iterdir():
                if not path.is_file():
                    continue
                name = path.name
                owned = bool(FILE_RE.match(name)) or (
                    name.endswith(".mp4.part") and bool(FILE_RE.match(name[:-5]))
                )
                if owned and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            with contextlib.suppress(OSError):
                folder.rmdir()
        except OSError as exc:
            _warn(f"could not clean {folder.name}: {exc}")
    if removed:
        _log(f"removed {removed} published file(s) older than {keep_days}d from {output}")
    return removed


def _require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise ConfigError(
            f"Missing required executable(s): {', '.join(missing)}. Install FFmpeg "
            "(with both ffmpeg and ffprobe) and make sure it is on PATH."
        )


def check_stream(settings: Settings) -> None:
    """Probe the camera's RTSP stream and fail with a clear error."""
    _require_ffmpeg()
    command = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "15000000",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height",
        "-of",
        "default=nw=1",
        build_rtsp_url(settings),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigError("Timed out probing the camera RTSP stream.") from exc
    except OSError as exc:
        raise ConfigError(f"Could not start ffprobe: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConfigError(
            f"Could not read the camera RTSP stream: {redact(detail) or 'ffprobe failed'}"
        )
    summary = result.stdout.strip().replace("\n", ", ")
    _log(f"RTSP stream OK: {summary}")


def _check_writable(directory: Path, label: str) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".tapo-nvr-write-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ConfigError(f"Cannot write to the {label} directory {directory}: {exc}") from exc


def _check_output(output: Path) -> None:
    """Require a writable output with a sentinel, so a missing mount is not recreated."""
    _check_writable(output, "output")
    sentinel = output / OUTPUT_SENTINEL_NAME
    if not sentinel.is_file():
        raise ConfigError(
            f"Output sentinel {sentinel} is missing. Create that file once after "
            "mounting the output folder; this prevents publishing into a local "
            "shadow when the Drive mount is unavailable."
        )


def _free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock(staging: Path) -> Path:
    """Create a single-instance lock for the staging directory."""
    lock = staging / LOCK_NAME
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            return lock
        except FileExistsError:
            try:
                pid = int(lock.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                raise ConfigError(
                    f"Another recorder (PID {pid}) is already using {staging}."
                ) from None
            with contextlib.suppress(OSError):
                lock.unlink()
    raise ConfigError(f"Could not acquire the recorder lock in {staging}.")


class Status:
    """Atomic JSON heartbeat for a headless recorder."""

    def __init__(
        self,
        path: Path,
        settings: Settings,
        staging: Path,
        output: Path,
    ) -> None:
        self.path = path
        self.data = {
            "schema": 1,
            "run_id": uuid.uuid4().hex,
            "pid": os.getpid(),
            "started_at": _utc_now(),
            "updated_at": _utc_now(),
            "state": "starting",
            "camera_host": settings.camera_host,
            "staging": str(staging),
            "output": str(output),
            "last_segment": None,
            "last_segment_write": None,
            "last_publish": None,
            "published_total": 0,
            "publish_failures": 0,
            "ffmpeg_pid": None,
            "ffmpeg_restarts": 0,
            "staging_bytes": 0,
            "free_bytes": 0,
            "exit_code": None,
            "last_error": None,
        }

    def update(self, **fields: object) -> None:
        self.data.update(fields)
        self.data["updated_at"] = _utc_now()
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            _warn(f"could not write status {self.path}: {exc}")
            with contextlib.suppress(OSError):
                temporary.unlink()


def _staging_state(staging: Path) -> tuple[float, int]:
    """Return (newest mtime, total size) for the staging MP4 files."""
    newest = 0.0
    total = 0
    for path in staging.glob("*.mp4"):
        try:
            info = path.stat()
            newest = max(newest, info.st_mtime)
            total += info.st_size
        except OSError:
            continue
    return newest, total


def _newest_segment(staging: Path) -> Path | None:
    files = [path for path in staging.glob("*.mp4") if FILE_RE.match(path.name)]
    if not files:
        return None
    return max(files, key=lambda path: _mtime(path, 0.0))


def _pump_stderr(proc: subprocess.Popen[str]) -> None:
    if proc.stderr is None:
        return
    try:
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                _warn(f"ffmpeg: {redact(text)}")
    except Exception as exc:  # noqa: BLE001 - the pump must never kill ffmpeg
        _warn(f"ffmpeg stderr pump stopped: {exc}")


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=FFMPEG_STOP_TIMEOUT_SECONDS)
        if proc.poll() is None:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=FFMPEG_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()


def _record_loop(
    settings: Settings,
    staging: Path,
    segment_seconds: int,
    stall_seconds: int,
    stop: threading.Event,
    status: Status,
) -> None:
    backoff = 5
    while not stop.is_set():
        _log("starting ffmpeg")
        status.update(state="starting_ffmpeg")
        popen_kwargs: dict[str, object] = {
            "stderr": subprocess.PIPE,
            "text": True,
            "errors": "replace",
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(
                build_ffmpeg_command(settings, staging, segment_seconds),
                **popen_kwargs,
            )
        except OSError as exc:
            _error(f"could not start ffmpeg: {exc}")
            status.update(state="error", last_error=str(exc))
            stop.wait(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        status.update(state="recording", ffmpeg_pid=proc.pid)
        threading.Thread(target=_pump_stderr, args=(proc,), daemon=True).start()
        started = time.monotonic()
        last_activity = _staging_state(staging)
        last_progress = time.monotonic()
        while proc.poll() is None and not stop.is_set():
            time.sleep(2)
            activity = _staging_state(staging)
            if activity != last_activity:
                last_activity = activity
                last_progress = time.monotonic()
            elif stall_seconds > 0 and time.monotonic() - last_progress > stall_seconds:
                _error(f"no segment progress for {stall_seconds}s; restarting ffmpeg")
                status.update(state="stalled", last_error="no segment progress")
                _stop_process(proc)
                break
        if stop.is_set():
            _stop_process(proc)
            return

        runtime = time.monotonic() - started
        backoff = 5 if runtime > 300 else min(backoff * 2, MAX_BACKOFF_SECONDS)
        restarts = int(status.data.get("ffmpeg_restarts") or 0) + 1
        status.update(ffmpeg_restarts=restarts, ffmpeg_pid=None)
        _warn(f"ffmpeg exited ({proc.returncode}); retrying in {backoff}s")
        stop.wait(backoff)


def _guarded_housekeeping(label: str, action) -> None:
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - housekeeping must not stop recording
        _error(f"{label} failed: {exc}")


def run_record(
    settings: Settings,
    *,
    output: Path | None = None,
    staging: Path | None = None,
    segment_seconds: int | None = None,
    keep_hours: int | None = None,
    output_keep_days: int | None = None,
    min_free_gb: int | None = None,
    stall_seconds: int | None = None,
    log_file: Path | None = None,
    status_file: Path | None = None,
    check: bool = False,
) -> int:
    """Record until interrupted, or run a one-shot preflight when ``check`` is set."""
    settings.require_record()
    _require_ffmpeg()
    staging_dir = (staging or settings.record_staging_path()).expanduser()
    output_dir = (output or settings.record_output_path()).expanduser()
    segment = settings.record_segment_seconds if segment_seconds is None else segment_seconds
    keep = settings.record_keep_hours if keep_hours is None else keep_hours
    output_keep = settings.record_output_keep_days if output_keep_days is None else output_keep_days
    min_free = settings.record_min_free_gb if min_free_gb is None else min_free_gb
    stall = settings.record_stall_seconds if stall_seconds is None else stall_seconds
    log_path = log_file or settings.record_log_path(staging_dir)
    status_path = status_file or settings.record_status_path(staging_dir)

    if not 60 <= segment <= 21600:
        raise ConfigError("RECORD_SEGMENT_SECONDS must be between 60 and 21600.")
    if not 0 <= keep <= 8760:
        raise ConfigError("RECORD_KEEP_HOURS must be between 0 and 8760.")
    if not 0 <= output_keep <= 3650:
        raise ConfigError("RECORD_OUTPUT_KEEP_DAYS must be between 0 and 3650.")
    if min_free < 0:
        raise ConfigError("RECORD_MIN_FREE_GB cannot be negative.")
    if stall < 0:
        raise ConfigError("RECORD_STALL_SECONDS cannot be negative.")
    if "%" in str(staging_dir):
        raise ConfigError(
            "RECORD_STAGING_DIR cannot contain '%' because ffmpeg uses it for strftime."
        )

    staging_resolved = staging_dir.resolve()
    output_resolved = output_dir.resolve()
    if (
        staging_resolved == output_resolved
        or output_resolved in staging_resolved.parents
        or staging_resolved in output_resolved.parents
    ):
        raise ConfigError("RECORD_STAGING_DIR and RECORD_OUTPUT_DIR must not overlap.")

    configure_logging(log_path)
    _check_writable(staging_dir, "staging")
    _check_output(output_dir)

    if check:
        check_stream(settings)
        _log(f"Recording would write {staging_dir} and publish to {output_dir}")
        return 0

    try:
        check_stream(settings)
    except ConfigError as exc:
        message = str(exc)
        if "401" in message or "Unauthorized" in message:
            raise
        _warn(f"warning: {message}; the recorder will keep retrying")

    lock = acquire_lock(staging_dir)
    status = Status(status_path, settings, staging_dir, output_dir)
    status.update(state="starting")
    stop = threading.Event()
    recorder: threading.Thread | None = None
    exit_code = 0
    try:
        recorder = threading.Thread(
            target=_record_loop,
            args=(settings, staging_dir, segment, stall, stop, status),
            daemon=True,
        )
        recorder.start()

        def startup_publish() -> None:
            published, failed = publish_pending(staging_dir, output_dir, min_age_seconds=0)
            if published or failed:
                _log(f"startup publish: {published} published, {failed} failed")

        _guarded_housekeeping("startup publish", startup_publish)
        _log(f"camera: {settings.camera_host} ({settings.camera_record_stream})")
        _log(f"staging: {staging_dir}")
        _log(f"publish: {output_dir}")
        retention = f"{output_keep}d" if output_keep else "forever"
        _log(f"segments: {segment // 60} min; local grace: {keep}h; output keep: {retention}")
        status.update(state="recording")

        while not stop.is_set():
            stop.wait(PUBLISH_INTERVAL_SECONDS)
            if stop.is_set():
                break
            if recorder is not None and not recorder.is_alive():
                _error("recorder stopped unexpectedly; exiting so a supervisor can restart it")
                status.update(state="error", last_error="recorder thread stopped")
                exit_code = 1
                break

            free = _free_bytes(staging_dir)
            newest = _newest_segment(staging_dir)
            status.update(
                free_bytes=free,
                staging_bytes=_staging_state(staging_dir)[1],
                last_segment=newest.name if newest else None,
                last_segment_write=(
                    datetime.fromtimestamp(_mtime(newest, 0), timezone.utc).isoformat()
                    if newest
                    else None
                ),
            )
            if min_free > 0 and free and free < min_free * 1_000_000_000:
                _error(f"staging free space below {min_free} GB; stopping")
                status.update(state="paused", last_error="staging free space low")
                exit_code = 3
                break

            _guarded_housekeeping(
                "publish",
                lambda: _log_publish(
                    publish_pending(staging_dir, output_dir),
                    status,
                ),
            )
            _guarded_housekeeping(
                "local cleanup",
                lambda: cleanup_published(staging_dir, output_dir, keep),
            )
            _guarded_housekeeping(
                "output retention",
                lambda: cleanup_output(output_dir, output_keep),
            )
    except KeyboardInterrupt:
        _log("stopping")
    finally:
        stop.set()
        if recorder is not None:
            recorder.join(timeout=FFMPEG_STOP_TIMEOUT_SECONDS + 5)
        _guarded_housekeeping(
            "final publish",
            lambda: publish_pending(staging_dir, output_dir, min_age_seconds=0),
        )
        _guarded_housekeeping(
            "final local cleanup",
            lambda: cleanup_published(staging_dir, output_dir, keep),
        )
        _guarded_housekeeping(
            "final output retention",
            lambda: cleanup_output(output_dir, output_keep),
        )
        status.update(state="stopped", exit_code=exit_code, ffmpeg_pid=None)
        with contextlib.suppress(OSError):
            lock.unlink()
        _log("stopped")
    return exit_code


def _log_publish(result: tuple[int, int], status: Status) -> None:
    published, failed = result
    if published:
        total = int(status.data.get("published_total") or 0) + published
        status.update(published_total=total, last_publish=_utc_now())
    if failed:
        failures = int(status.data.get("publish_failures") or 0) + failed
        status.update(publish_failures=failures)
