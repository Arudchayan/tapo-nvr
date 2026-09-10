"""Environment-file loading and validated configuration."""

from __future__ import annotations

import codecs
import ipaddress
import logging
import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

LOGGER = logging.getLogger(__name__)

DEFAULT_ALLOWED_CIDR = "100.64.0.0/10"
DEFAULT_BASE_PATH = "~/tapo-nvr"
DEFAULT_FRIGATE_IMAGE = "ghcr.io/blakeblackshear/frigate:stable"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

_CAMERA_NAME = re.compile(r"[A-Za-z0-9_]+")
_CONTAINER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_SHM_SIZE = re.compile(r"[0-9]+[bkmg]?", re.IGNORECASE)
_BOMS = (
    codecs.BOM_UTF16_LE,
    codecs.BOM_UTF16_BE,
    codecs.BOM_UTF32_LE,
    codecs.BOM_UTF32_BE,
)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse a minimal dotenv document.

    Supports comments, blank lines, a leading ``export``, unquoted values with
    whitespace-prefixed comments, and single- or double-quoted values. Values
    are never interpolated. Duplicate keys are last-wins.
    """
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ConfigError(f"Invalid configuration line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"Invalid configuration line {line_number}: empty key")
        values[key] = _clean_value(value.strip(), line_number)
    return values


def _clean_value(value: str, line_number: int) -> str:
    if not value:
        return ""
    if value[0] in {'"', "'"}:
        quote = value[0]
        end = value.find(quote, 1)
        if end == -1:
            raise ConfigError(f"Invalid configuration line {line_number}: unterminated quote")
        return value[1:end]
    comment = value.find(" #")
    if comment != -1:
        value = value[:comment]
    return value.strip()


def load_env_file(path: str | Path) -> dict[str, str]:
    """Read and parse a UTF-8 (optionally BOM-prefixed) environment file."""
    env_path = Path(path)
    try:
        data = env_path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Configuration file not found: {env_path}. Copy .env.example to .env and edit it."
        ) from exc
    if data.startswith(_BOMS):
        raise ConfigError(f"{env_path} is UTF-16 or UTF-32 encoded. Save it as UTF-8 and retry.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{env_path} is not valid UTF-8: {exc}") from exc
    return parse_dotenv(text)


def parse_networks(values: Sequence[str]) -> tuple[Network, ...]:
    """Parse comma-separated CIDR ranges, falling back to the Tailscale range."""
    networks: list[Network] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                networks.append(ipaddress.ip_network(part, strict=False))
            except ValueError as exc:
                raise ConfigError(f"Invalid CIDR range: {part!r}") from exc
    if not networks:
        networks.append(ipaddress.ip_network(DEFAULT_ALLOWED_CIDR))
    return tuple(networks)


def resolve_remote_base(home: str, base_path: str) -> str:
    """Resolve ``NVR_BASE_PATH`` against the remote user's home directory."""
    value = (base_path or DEFAULT_BASE_PATH).strip()
    home = home.rstrip("/") or "/"
    if value.startswith("~"):
        if value not in {"~"} and not value.startswith("~/"):
            raise ConfigError(
                "NVR_BASE_PATH cannot use '~user' syntax; use an absolute path "
                "or a path starting with '~/'."
            )
        suffix = value[1:].lstrip("/")
        resolved = posixpath.join(home, suffix) if suffix else home
    elif value.startswith("/"):
        resolved = value.rstrip("/") or "/"
    else:
        raise ConfigError("NVR_BASE_PATH must be an absolute path or start with '~/'.")
    if resolved in {"/", home}:
        raise ConfigError(
            "NVR_BASE_PATH must be a dedicated subdirectory, not the home "
            "directory or the filesystem root."
        )
    return resolved


@dataclass(frozen=True)
class Settings:
    """Validated settings.

    Almost every field maps to the same-named upper-case environment key, for
    example ``camera_host`` is read from ``CAMERA_HOST``. The exception is
    ``relay_allowed_cidrs``, which is read from the comma-separated
    ``RELAY_ALLOWED_CIDR``.
    """

    # Camera
    camera_host: str = ""
    camera_rtsp_port: int = 554
    camera_username: str = ""
    camera_password: str = ""
    camera_record_stream: str = "stream1"
    camera_detect_stream: str = "stream2"
    camera_detect_width: int = 640
    camera_detect_height: int = 360
    camera_detect_fps: int = 5
    camera_objects: tuple[str, ...] = ("person", "cat", "dog")

    # Relay host
    relay_host: str = "auto"
    relay_port: int = 8554
    relay_allowed_cidrs: tuple[str, ...] = (DEFAULT_ALLOWED_CIDR,)

    # NVR host
    nvr_host: str = ""
    nvr_ssh_port: int = 22
    nvr_ssh_user: str = ""
    nvr_ssh_password: str = ""
    nvr_ssh_key: str = ""
    nvr_strict_host_key_checking: bool = True
    nvr_base_path: str = DEFAULT_BASE_PATH

    # Frigate
    frigate_camera_name: str = "tapo_c220"
    frigate_container_name: str = "tapo-frigate"
    frigate_image: str = DEFAULT_FRIGATE_IMAGE
    frigate_ui_port: int = 8971
    frigate_gpu: str = "auto"
    frigate_storage_path: str = ""
    frigate_shm_size: str = "64m"
    retention_days: int = 30
    motion_retention_days: int = 3

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> Settings:
        """Build validated settings from environment-style keys."""

        def text(name: str, default: str = "") -> str:
            raw = mapping.get(name)
            if raw is None:
                return default
            value = str(raw).strip()
            return value if value else default

        def secret(name: str) -> str:
            # Quoted values may intentionally contain leading/trailing spaces.
            raw = mapping.get(name)
            return "" if raw is None else str(raw)

        def integer(
            name: str,
            default: int,
            *,
            minimum: int = 1,
            maximum: int = 65535,
        ) -> int:
            raw = text(name, "")
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
            if not minimum <= value <= maximum:
                raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
            return value

        def boolean(name: str, default: bool) -> bool:
            raw = text(name, "").lower()
            if not raw:
                return default
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
            raise ConfigError(f"{name} must be a boolean, got {raw!r}")

        known = {field.name.upper() for field in fields(cls)}
        known.discard("RELAY_ALLOWED_CIDRS")
        known.add("RELAY_ALLOWED_CIDR")
        known.add("PYTHON_PATH")  # consumed by the Windows install scripts
        for key in sorted(set(mapping) - known):
            LOGGER.warning("Ignoring unknown setting %s", key)

        camera_name = text("FRIGATE_CAMERA_NAME", "tapo_c220")
        if not _CAMERA_NAME.fullmatch(camera_name):
            raise ConfigError(
                "FRIGATE_CAMERA_NAME may only contain letters, digits and underscores."
            )

        container_name = text("FRIGATE_CONTAINER_NAME", "tapo-frigate")
        if not _CONTAINER_NAME.fullmatch(container_name):
            raise ConfigError(
                f"FRIGATE_CONTAINER_NAME is not a valid container name: {container_name!r}"
            )

        gpu = text("FRIGATE_GPU", "auto").lower()
        if gpu not in {"auto", "vaapi", "none"}:
            raise ConfigError("FRIGATE_GPU must be one of: auto, vaapi, none")

        shm_size = text("FRIGATE_SHM_SIZE", "64m")
        if not _SHM_SIZE.fullmatch(shm_size):
            raise ConfigError(f"FRIGATE_SHM_SIZE is not a valid Docker size: {shm_size!r}")

        objects = tuple(
            item.strip()
            for item in text("CAMERA_OBJECTS", "person,cat,dog").split(",")
            if item.strip()
        )
        if not objects:
            raise ConfigError("CAMERA_OBJECTS must list at least one object label.")

        allowed = tuple(
            str(network)
            for network in parse_networks([text("RELAY_ALLOWED_CIDR", DEFAULT_ALLOWED_CIDR)])
        )

        return cls(
            camera_host=text("CAMERA_HOST"),
            camera_rtsp_port=integer("CAMERA_RTSP_PORT", 554),
            camera_username=text("CAMERA_USERNAME"),
            camera_password=secret("CAMERA_PASSWORD"),
            camera_record_stream=text("CAMERA_RECORD_STREAM", "stream1"),
            camera_detect_stream=text("CAMERA_DETECT_STREAM", "stream2"),
            camera_detect_width=integer("CAMERA_DETECT_WIDTH", 640, maximum=16384),
            camera_detect_height=integer("CAMERA_DETECT_HEIGHT", 360, maximum=16384),
            camera_detect_fps=integer("CAMERA_DETECT_FPS", 5, maximum=60),
            camera_objects=objects,
            relay_host=text("RELAY_HOST", "auto"),
            relay_port=integer("RELAY_PORT", 8554),
            relay_allowed_cidrs=allowed,
            nvr_host=text("NVR_HOST"),
            nvr_ssh_port=integer("NVR_SSH_PORT", 22),
            nvr_ssh_user=text("NVR_SSH_USER"),
            nvr_ssh_password=secret("NVR_SSH_PASSWORD"),
            nvr_ssh_key=text("NVR_SSH_KEY"),
            nvr_strict_host_key_checking=boolean("NVR_STRICT_HOST_KEY_CHECKING", True),
            nvr_base_path=text("NVR_BASE_PATH", DEFAULT_BASE_PATH),
            frigate_camera_name=camera_name,
            frigate_container_name=container_name,
            frigate_image=text("FRIGATE_IMAGE", DEFAULT_FRIGATE_IMAGE),
            frigate_ui_port=integer("FRIGATE_UI_PORT", 8971),
            frigate_gpu=gpu,
            frigate_storage_path=text("FRIGATE_STORAGE_PATH"),
            frigate_shm_size=shm_size,
            retention_days=integer("RETENTION_DAYS", 30, minimum=0, maximum=3650),
            motion_retention_days=integer("MOTION_RETENTION_DAYS", 3, minimum=0, maximum=3650),
        )

    def require(self, *names: str) -> None:
        """Raise :class:`ConfigError` when any named field is empty."""
        missing = [name for name in names if not getattr(self, name)]
        if missing:
            keys = ", ".join(name.upper() for name in missing)
            raise ConfigError(f"Missing required setting(s): {keys}")

    def require_camera(self) -> None:
        """Validate the camera settings."""
        self.require("camera_host", "camera_username", "camera_password")

    def require_nvr(self) -> None:
        """Validate the NVR connection settings."""
        self.require("nvr_host", "nvr_ssh_user")
        if not self.nvr_ssh_password and not self.nvr_ssh_key:
            raise ConfigError(
                "Set NVR_SSH_KEY or NVR_SSH_PASSWORD to authenticate to the NVR host."
            )

    def remote_storage_dir(self, home: str, base: str) -> str:
        """Return the absolute remote path used for recordings."""
        if self.frigate_storage_path.strip():
            return resolve_remote_base(home, self.frigate_storage_path)
        return f"{base}/frigate/storage"
