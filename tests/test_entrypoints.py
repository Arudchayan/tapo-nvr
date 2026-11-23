"""Smoke tests for the module entry points."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tapo_nvr.cli import build_parser
from tapo_nvr.sync import DEFAULT_DAYS


def test_main_module_prints_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tapo_nvr", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "tapo-nvr" in result.stdout


def test_relay_module_prints_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tapo_nvr.relay", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "tapo-nvr relay" in result.stdout


def test_sync_help_mentions_the_output_directory() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tapo_nvr", "sync", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "--output" in result.stdout
    assert "--days" in result.stdout


def test_record_help_mentions_the_check_flag() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tapo_nvr", "record", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "--check" in result.stdout
    assert "--staging-dir" in result.stdout


def test_sync_parser_collects_repeated_dates() -> None:
    args = build_parser().parse_args(["sync", "--date", "2026-11-01", "--date", "2026-11-02"])

    assert args.dates == ["2026-11-01", "2026-11-02"]
    assert args.days == DEFAULT_DAYS


def test_deploy_dry_run_from_the_cli(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CAMERA_HOST=192.168.1.50\n"
        "CAMERA_USERNAME=camera-user\n"
        "CAMERA_PASSWORD=secret\n"
        "RELAY_HOST=relay.local\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tapo_nvr",
            "deploy",
            "--dry-run",
            "--env",
            str(env_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "{FRIGATE_CAMERA_PASSWORD}" in result.stdout
    assert "secret" not in result.stdout
