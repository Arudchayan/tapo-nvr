"""Health checks for the relay host and the NVR host."""

from __future__ import annotations

import re
import shlex
import socket
import subprocess
from dataclasses import asdict, dataclass

from .config import ConfigError, Settings, resolve_remote_base
from .frigate import GPU_DEVICE
from .relay import resolve_relay_host
from .ssh import CommandResult, SSHClient
from .util import redact


@dataclass(frozen=True)
class Check:
    """The result of a single health check."""

    ok: bool
    output: str = ""
    error: str = ""


def _check_from_result(result: CommandResult) -> Check:
    return Check(result.ok, output=redact(result.output), error=redact(result.error))


def check_tcp(host: str, port: int, timeout: float = 3.0) -> Check:
    """Check whether a TCP port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return Check(True, output=f"{host}:{port} is reachable")
    except OSError as exc:
        return Check(False, error=f"{host}:{port} is not reachable ({exc})")


def _run_local(command: list[str], timeout: float = 10.0) -> Check:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except OSError as exc:
        return Check(False, error=str(exc))
    output = (result.stdout or result.stderr).strip()
    return Check(result.returncode == 0, output=redact(output))


def local_checks(settings: Settings) -> dict[str, Check]:
    """Run the checks that only make sense on the relay host."""
    checks: dict[str, Check] = {}
    if settings.camera_host:
        checks["camera_rtsp"] = check_tcp(settings.camera_host, settings.camera_rtsp_port)
    try:
        relay_host = resolve_relay_host(settings.relay_host)
    except ConfigError as exc:
        checks["relay_listening"] = Check(False, error=str(exc))
    else:
        checks["relay_listening"] = check_tcp(relay_host, settings.relay_port)
    checks["tailscale"] = _run_local(["tailscale", "status", "--peers=false"])
    return checks


def _relay_probe(host: str, port: int) -> str:
    parts = []
    if re.fullmatch(r"[A-Za-z0-9.\-]+", host):
        parts.append(f"timeout 3 bash -c '</dev/tcp/{host}/{port}' >/dev/null 2>&1")
    parts.append(f"nc -z -w 3 {shlex.quote(host)} {port} >/dev/null 2>&1")
    return "if {}; then echo open; else echo closed; fi".format(" || ".join(parts))


def remote_checks(settings: Settings) -> dict[str, Check]:
    """Run the checks that require an SSH connection to the NVR host."""
    settings.require_nvr()
    relay_host = resolve_relay_host(settings.relay_host)
    container = settings.frigate_container_name
    with SSHClient(settings) as ssh:
        home = ssh.home()
        base = resolve_remote_base(home, settings.nvr_base_path)
        storage = settings.remote_storage_dir(home, base)
        checks = {
            "system": _check_from_result(ssh.run("uname -srmo")),
            "docker": _check_from_result(ssh.run("docker --version")),
            "storage": _check_from_result(ssh.run(f"df -h {shlex.quote(storage)}")),
            "gpu_device": _check_from_result(
                ssh.run(f"test -e {shlex.quote(GPU_DEVICE)} && ls -1 {shlex.quote(GPU_DEVICE)}")
            ),
            "relay_reachability": _check_from_result(
                ssh.run(_relay_probe(relay_host, settings.relay_port))
            ),
            "container": _check_from_result(
                ssh.run(
                    "docker ps --filter "
                    + shlex.quote(f"name=^/{container}$")
                    + " --format {{.Status}}"
                )
            ),
            "image": _check_from_result(
                ssh.run(
                    "docker images "
                    + shlex.quote(settings.frigate_image)
                    + " --format {{.Repository}}:{{.Tag}}"
                )
            ),
            "recent_logs": _check_from_result(
                ssh.run(
                    f"docker logs --since 5m {shlex.quote(container)} 2>&1 "
                    "| grep -Ei 'error|unable|failed|invalid' | tail -n 20 || true"
                )
            ),
            "tailscale": _check_from_result(ssh.run("tailscale status | head -5")),
        }
    return checks


def run_inspect(settings: Settings, scope: str = "all") -> dict[str, object]:
    """Run the requested checks and return a JSON-serialisable report."""
    report: dict[str, object] = {}
    if scope in {"all", "local"}:
        report["local"] = {name: asdict(check) for name, check in local_checks(settings).items()}
    if scope in {"all", "remote"}:
        try:
            report["remote"] = {
                name: asdict(check) for name, check in remote_checks(settings).items()
            }
        except ConfigError as exc:
            report["remote"] = {"error": str(exc)}
    return report
