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
from .relay import main as relay_main


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="tapo-nvr",
        description=("Private, camera-only RTSP relay for a self-hosted Frigate NVR."),
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
        return relay_main(raw[1:])

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
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 2
