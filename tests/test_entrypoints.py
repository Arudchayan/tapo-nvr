"""Smoke tests for the module entry points."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
