"""Fetch the most recent recorded clip from the NVR host."""

from __future__ import annotations

import shlex
from pathlib import Path

from .config import ConfigError, Settings, resolve_remote_base
from .ssh import SSHClient


def fetch_latest_clip(settings: Settings, output: Path) -> Path | None:
    """Download the newest MP4 under the Frigate storage directory."""
    settings.require_nvr()
    with SSHClient(settings) as ssh:
        home = ssh.home()
        base = resolve_remote_base(home, settings.nvr_base_path)
        storage = settings.remote_storage_dir(home, base)

        check = ssh.run(f"test -d {shlex.quote(storage)}")
        if not check.ok:
            raise ConfigError(f"Storage directory does not exist on the NVR host: {storage}")

        listing = ssh.run(
            f"find {shlex.quote(storage)} -type f -name '*.mp4' -printf '%T@ %p\\n' "
            "| sort -nr | head -1"
        )
        if not listing.ok or listing.error:
            detail = listing.error or listing.output or "unknown error"
            raise ConfigError(f"Could not search for recordings: {detail}")
        latest = listing.output.strip()
        if not latest:
            return None
        _, remote_path = latest.split(" ", 1)
        sftp = ssh.open_sftp()
        try:
            sftp.get(remote_path, str(output))
        finally:
            sftp.close()
    return output
