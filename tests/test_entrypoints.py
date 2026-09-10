"""Smoke tests for the module entry points."""

from __future__ import annotations

import subprocess
import sys


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
