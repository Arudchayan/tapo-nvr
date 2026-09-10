"""Tests for inspect check semantics using a fake SSH client."""

from __future__ import annotations

from tapo_nvr.config import Settings
from tapo_nvr.inspect import _relay_probe, collect_remote_checks
from tapo_nvr.ssh import CommandResult


class FakeSSH:
    """Minimal stand-in for :class:`tapo_nvr.ssh.SSHClient`."""

    def __init__(self, responses: dict[str, CommandResult]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    def home(self) -> str:
        return "/home/nvr"

    def run(self, command: str, timeout: float = 300.0) -> CommandResult:
        self.commands.append(command)
        for needle, result in self.responses.items():
            if needle in command:
                return result
        return CommandResult(True, 0, "", "")


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"relay_host": "relay.local", "frigate_gpu": "none"}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_relay_probe_exits_nonzero_when_closed() -> None:
    assert "exit 1" in _relay_probe("relay.local", 8554)


def test_relay_reachability_reports_closed_ports() -> None:
    ssh = FakeSSH({"/dev/tcp/relay.local/8554": CommandResult(False, 1, "closed", "")})

    checks = collect_remote_checks(_settings(), ssh)

    assert checks["relay_reachability"].ok is False


def test_container_must_be_running() -> None:
    ssh = FakeSSH({"docker inspect -f": CommandResult(True, 0, "false", "")})

    checks = collect_remote_checks(_settings(), ssh)

    assert checks["container"].ok is False


def test_missing_container_is_reported() -> None:
    ssh = FakeSSH({"docker inspect -f": CommandResult(False, 1, "", "No such object")})

    checks = collect_remote_checks(_settings(), ssh)

    assert checks["container"].ok is False
    assert "No such object" in checks["container"].error


def test_missing_image_is_reported() -> None:
    ssh = FakeSSH({"docker image inspect": CommandResult(False, 1, "", "No such image")})

    checks = collect_remote_checks(_settings(), ssh)

    assert checks["image"].ok is False


def test_gpu_check_is_skipped_when_disabled() -> None:
    checks = collect_remote_checks(_settings(frigate_gpu="none"), FakeSSH({}))

    assert "gpu_device" not in checks


def test_gpu_check_is_informational_when_auto() -> None:
    ssh = FakeSSH({"test -e": CommandResult(False, 1, "", "missing")})

    checks = collect_remote_checks(_settings(frigate_gpu="auto"), ssh)

    assert checks["gpu_device"].ok is True


def test_recent_logs_are_informational() -> None:
    ssh = FakeSSH({"docker logs": CommandResult(False, 1, "", "Error: No such container")})

    checks = collect_remote_checks(_settings(), ssh)

    assert checks["recent_logs"].ok is True
