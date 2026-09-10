"""Tests for the deploy flow using a fake SSH client."""

from __future__ import annotations

from typing import Any

import pytest

from tapo_nvr import deploy as deploy_module
from tapo_nvr.config import ConfigError, Settings
from tapo_nvr.ssh import CommandResult


class FakeSSH:
    """Stand-in for :class:`tapo_nvr.ssh.SSHClient`."""

    def __init__(self, responses: dict[str, CommandResult] | None = None) -> None:
        self.responses = responses or {}
        self.commands: list[str] = []
        self.files: dict[str, str] = {}
        self.joined: list[str] = []

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def home(self) -> str:
        return "/home/nvr"

    def run(self, command: str, timeout: float = 300.0) -> CommandResult:
        self.commands.append(command)
        for needle, result in self.responses.items():
            if needle in command:
                return result
        return CommandResult(True, 0, "", "")

    def run_ok(self, command: str, message: str, timeout: float = 300.0) -> CommandResult:
        result = self.run(command, timeout=timeout)
        if not result.ok:
            raise ConfigError(f"{message}: {result.error or result.output}")
        return result

    def put_file(self, remote_path: str, content: str, mode: int = 0o600) -> None:
        self.files[remote_path] = content


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "camera_host": "192.168.1.50",
        "camera_username": "camera-user",
        "camera_password": "p@ss",
        "relay_host": "relay.local",
        "nvr_host": "nvr.local",
        "nvr_ssh_user": "nvr-admin",
        "nvr_ssh_password": "secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_dry_run_needs_no_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(relay_host="relay.local")

    deploy_module.deploy(settings, dry_run=True)

    output = capsys.readouterr().out
    assert "{FRIGATE_CAMERA_PASSWORD}" in output
    assert "frigate/config/config.yml" in output
    assert "frigate/frigate.env" in output


def test_deploy_reports_unreachable_docker_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSSH({"docker info": CommandResult(False, 1, "", "permission denied")})
    monkeypatch.setattr(deploy_module, "SSHClient", lambda settings: fake)

    with pytest.raises(ConfigError, match="Docker daemon"):
        deploy_module.deploy(_settings())


def test_deploy_writes_frigate_paths_and_binds_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSSH(
        {
            "docker inspect --type container": CommandResult(False, 1, "", "No such object"),
            "tailscale ip -4": CommandResult(True, 0, "100.64.0.9", ""),
            "docker inspect -f": CommandResult(True, 0, "true", ""),
        }
    )
    monkeypatch.setattr(deploy_module, "SSHClient", lambda settings: fake)

    deploy_module.deploy(_settings(), pull=False)

    assert "/home/nvr/tapo-nvr/frigate/config/config.yml" in fake.files
    assert "/home/nvr/tapo-nvr/frigate/frigate.env" in fake.files
    run_commands = [command for command in fake.commands if command.startswith("docker run")]
    assert run_commands
    assert "-p 100.64.0.9:8971:8971" in run_commands[0]
    assert "/home/nvr/tapo-nvr/frigate/storage" in run_commands[0]
