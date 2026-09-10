"""SSH helpers for talking to the NVR host."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paramiko

from .config import ConfigError, Settings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    """The outcome of a remote command."""

    ok: bool
    exit_code: int
    output: str
    error: str


class SSHClient:
    """Context manager that keeps one authenticated SSH connection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = paramiko.SSHClient()

    def __enter__(self) -> SSHClient:
        settings = self._settings
        if settings.nvr_strict_host_key_checking:
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
            self._client.load_system_host_keys()
        else:
            LOGGER.warning(
                "SSH host key verification is disabled; "
                "set NVR_STRICT_HOST_KEY_CHECKING=true when possible."
            )
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, Any] = {
            "hostname": settings.nvr_host,
            "port": settings.nvr_ssh_port,
            "username": settings.nvr_ssh_user,
            "timeout": 15,
            "banner_timeout": 15,
            "auth_timeout": 15,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if settings.nvr_ssh_key:
            key_path = Path(settings.nvr_ssh_key).expanduser()
            if not key_path.is_file():
                raise ConfigError(f"SSH key not found: {key_path}")
            connect_kwargs["key_filename"] = str(key_path)
        else:
            connect_kwargs["password"] = settings.nvr_ssh_password

        try:
            self._client.connect(**connect_kwargs)
        except (paramiko.SSHException, OSError) as exc:
            self._client.close()
            raise ConfigError(f"SSH connection to {settings.nvr_host} failed: {exc}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._client.close()

    @staticmethod
    def _drain(recv: Any, sink: bytearray, errors: list[Exception]) -> None:
        try:
            while True:
                data = recv(65536)
                if not data:
                    return
                sink.extend(data)
        except Exception as exc:  # surfaced to the caller as a failed command
            errors.append(exc)

    def run(self, command: str, timeout: float = 300.0) -> CommandResult:
        """Run a command and return its output without deadlocking on buffers."""
        transport = self._client.get_transport()
        if transport is None or not transport.is_active():
            raise ConfigError("The SSH connection is no longer active.")
        channel = transport.open_session(timeout=15)
        channel.settimeout(timeout)
        channel.exec_command(command)

        stdout = bytearray()
        stderr = bytearray()
        errors: list[Exception] = []
        threads = [
            threading.Thread(target=self._drain, args=(channel.recv, stdout, errors), daemon=True),
            threading.Thread(
                target=self._drain,
                args=(channel.recv_stderr, stderr, errors),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        exit_code = -1 if errors else channel.recv_exit_status()
        channel.close()

        return CommandResult(
            ok=not errors and exit_code == 0,
            exit_code=exit_code,
            output=stdout.decode(errors="replace").strip(),
            error=stderr.decode(errors="replace").strip()
            or "; ".join(str(error) for error in errors),
        )

    def run_ok(self, command: str, message: str, timeout: float = 300.0) -> CommandResult:
        """Run a command and raise :class:`ConfigError` when it fails."""
        result = self.run(command, timeout=timeout)
        if not result.ok:
            detail = result.error or result.output or "unknown error"
            raise ConfigError(f"{message}: {detail}")
        return result

    def home(self) -> str:
        """Return the remote user's home directory."""
        sftp = self._client.open_sftp()
        try:
            home = sftp.normalize(".")
        finally:
            sftp.close()
        if home and home.startswith("/"):
            return home.rstrip("/") or "/"
        return self.run('printf %s "$HOME"').output or "/"

    def open_sftp(self) -> paramiko.SFTPClient:
        """Open an SFTP session on this connection."""
        return self._client.open_sftp()

    def put_file(self, remote_path: str, content: str, mode: int = 0o600) -> None:
        """Write a file over SFTP and restrict its permissions."""
        sftp = self.open_sftp()
        try:
            with sftp.file(remote_path, "w") as remote:
                remote.write(content)
            sftp.chmod(remote_path, mode)
        finally:
            sftp.close()
