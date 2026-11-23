"""Command-line interface for tapo-nvr."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .clip import fetch_latest_clip
from .config import ConfigError, Settings, load_env_file
from .deploy import deploy
from .inspect import run_inspect
from .record import run_record
from .relay import main as relay_main
from .sync import DEFAULT_DAYS, run_sync


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="tapo-nvr",
        description=(
            "Private RTSP relay, laptop recorder, and SD-card backup for Tapo "
            "cameras and Frigate NVRs."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Write the Frigate configuration and (re)create the container.",
    )
    deploy_parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the environment file (default: ./.env).",
    )
    deploy_parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Skip 'docker pull' before starting the container.",
    )
    deploy_parser.add_argument(
        "--gpu",
        choices=["auto", "vaapi", "none"],
        default=None,
        help="Override FRIGATE_GPU for this run.",
    )
    deploy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deployed without connecting to the NVR.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect", help="Check the relay host and the Frigate NVR."
    )
    inspect_parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the environment file (default: ./.env).",
    )
    inspect_parser.add_argument(
        "--scope",
        choices=["all", "local", "remote"],
        default="all",
        help="Which checks to run (default: all).",
    )

    clip_parser = subparsers.add_parser(
        "fetch-clip", help="Download the most recent recording from the NVR."
    )
    clip_parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the environment file (default: ./.env).",
    )
    clip_parser.add_argument(
        "--output",
        type=Path,
        default=Path("latest-clip.mp4"),
        help="Where to write the downloaded clip.",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Download new camera SD-card recordings to a folder.",
    )
    sync_parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the environment file (default: ./.env).",
    )
    sync_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Destination directory (overrides SYNC_OUTPUT_DIR). Point it at a "
            "Google Drive folder for offsite backup."
        ),
    )
    sync_parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Days to check, including today (default: {DEFAULT_DAYS}).",
    )
    sync_parser.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help="Check from this date through today.",
    )
    sync_parser.add_argument(
        "--date",
        action="append",
        default=[],
        dest="dates",
        metavar="YYYY-MM-DD",
        help="Check one date; repeat for several. Overrides --days and --since.",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List recordings without downloading anything.",
    )
    sync_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Download clips that already exist in the output directory.",
    )

    record_parser = subparsers.add_parser(
        "record",
        help="Record the camera RTSP stream continuously to a folder.",
    )
    record_parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the environment file (default: ./.env).",
    )
    record_parser.add_argument(
        "--check",
        action="store_true",
        help="Probe the stream and output folder, then exit.",
    )
    record_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Publish directory (overrides RECORD_OUTPUT_DIR). Point it at a Google Drive folder."
        ),
    )
    record_parser.add_argument(
        "--staging-dir",
        type=Path,
        default=None,
        help="Local staging directory (overrides RECORD_STAGING_DIR).",
    )
    record_parser.add_argument(
        "--segment-seconds",
        type=int,
        default=None,
        help="Segment length in seconds (overrides RECORD_SEGMENT_SECONDS).",
    )
    record_parser.add_argument(
        "--keep-hours",
        type=int,
        default=None,
        help="Hours to keep published segments locally (overrides RECORD_KEEP_HOURS).",
    )
    record_parser.add_argument(
        "--output-keep-days",
        type=int,
        default=None,
        help=(
            "Delete published files older than this many days (overrides "
            "RECORD_OUTPUT_KEEP_DAYS; 0 keeps everything)."
        ),
    )
    record_parser.add_argument(
        "--min-free-gb",
        type=int,
        default=None,
        help="Stop recording when staging has less free space (overrides RECORD_MIN_FREE_GB).",
    )
    record_parser.add_argument(
        "--stall-seconds",
        type=int,
        default=None,
        help="Restart ffmpeg after this many seconds without segment progress (0 disables).",
    )
    record_parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Rotating recorder log file (default: RECORD_LOG_FILE or <staging>/record.log).",
    )
    record_parser.add_argument(
        "--status-file",
        type=Path,
        default=None,
        help="JSON heartbeat file (default: RECORD_STATUS_FILE or <staging>/status.json).",
    )

    subparsers.add_parser(
        "relay",
        add_help=False,
        help="Run the camera-only RTSP relay (see 'tapo-nvr relay --help').",
    )
    return parser


def _load_settings(path: Path) -> Settings:
    return Settings.from_mapping(load_env_file(path))


def _has_failures(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("ok") is False:
            return True
        if "error" in value and "ok" not in value:
            return True
        return any(_has_failures(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_failures(item) for item in value)
    return False


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``tapo-nvr`` command."""
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "relay":
        try:
            return relay_main(raw[1:])
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    parser = build_parser()
    args = parser.parse_args(raw)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "deploy":
            settings = _load_settings(args.env)
            deploy(
                settings,
                pull=not args.no_pull,
                gpu=args.gpu,
                dry_run=args.dry_run,
            )
            return 0
        if args.command == "inspect":
            settings = _load_settings(args.env)
            report = run_inspect(settings, args.scope)
            print(json.dumps(report, indent=2))
            return 1 if _has_failures(report) else 0
        if args.command == "fetch-clip":
            settings = _load_settings(args.env)
            path = fetch_latest_clip(settings, args.output)
            if path is None:
                print("No recordings were found on the NVR yet.")
            else:
                print(f"Fetched {path} ({path.stat().st_size} bytes).")
            return 0
        if args.command == "sync":
            settings = _load_settings(args.env)
            return run_sync(
                settings,
                output=args.output,
                days=args.days,
                since=args.since,
                dates=args.dates,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
        if args.command == "record":
            settings = _load_settings(args.env)
            return run_record(
                settings,
                output=args.output,
                staging=args.staging_dir,
                segment_seconds=args.segment_seconds,
                keep_hours=args.keep_hours,
                output_keep_days=args.output_keep_days,
                min_free_gb=args.min_free_gb,
                stall_seconds=args.stall_seconds,
                log_file=args.log_file,
                status_file=args.status_file,
                check=args.check,
            )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 2
