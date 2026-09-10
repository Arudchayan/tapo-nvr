"""Frigate configuration rendering and container command construction."""

from __future__ import annotations

import shlex
from urllib.parse import quote

from .config import Settings

GPU_DEVICE = "/dev/dri/renderD128"
CACHE_TMPFS = "type=tmpfs,target=/tmp/cache,tmpfs-size=536870912"

_CAMERA_HOST = "{FRIGATE_CAMERA_HOST}"
_CAMERA_USERNAME = "{FRIGATE_CAMERA_USERNAME}"
_CAMERA_PASSWORD = "{FRIGATE_CAMERA_PASSWORD}"


def render_config(settings: Settings, gpu: str) -> str:
    """Render the Frigate ``config.yml`` for the relay."""
    lines: list[str] = ["mqtt:", "  enabled: false", ""]
    if gpu == "vaapi":
        lines += ["ffmpeg:", "  hwaccel_args: preset-vaapi", ""]
    lines += [
        "detectors:",
        "  cpu:",
        "    type: cpu",
        "",
        # Schema reference: https://docs.frigate.video/configuration/record/
        "record:",
        "  enabled: true",
        "  continuous:",
        "    days: 0",
        "  motion:",
        f"    days: {settings.motion_retention_days}",
        "  alerts:",
        "    retain:",
        f"      days: {settings.retention_days}",
        "      mode: motion",
        "  detections:",
        "    retain:",
        f"      days: {settings.retention_days}",
        "      mode: motion",
        "",
        "snapshots:",
        "  enabled: true",
        "  retain:",
        f"    default: {settings.retention_days}",
        "",
        "cameras:",
        f"  {settings.frigate_camera_name}:",
        "    ffmpeg:",
        "      inputs:",
        f"        - path: rtsp://{_CAMERA_USERNAME}:{_CAMERA_PASSWORD}@{_CAMERA_HOST}:{settings.relay_port}/{settings.camera_record_stream}",
        "          roles:",
        "            - record",
        f"        - path: rtsp://{_CAMERA_USERNAME}:{_CAMERA_PASSWORD}@{_CAMERA_HOST}:{settings.relay_port}/{settings.camera_detect_stream}",
        "          roles:",
        "            - detect",
        "    detect:",
        f"      width: {settings.camera_detect_width}",
        f"      height: {settings.camera_detect_height}",
        f"      fps: {settings.camera_detect_fps}",
        "    objects:",
        "      track:",
    ]
    lines += [f"        - {name}" for name in settings.camera_objects]
    return "\n".join(lines) + "\n"


def render_env(settings: Settings, relay_host: str) -> str:
    """Render the mode-0600 environment file consumed by Frigate."""
    return (
        f"FRIGATE_CAMERA_HOST={relay_host}\n"
        f"FRIGATE_CAMERA_USERNAME={quote(settings.camera_username, safe='')}\n"
        f"FRIGATE_CAMERA_PASSWORD={quote(settings.camera_password, safe='')}\n"
    )


def docker_run_command(
    settings: Settings,
    *,
    gpu: str,
    config_dir: str,
    storage_dir: str,
    env_path: str,
    bind_address: str,
) -> str:
    """Build the ``docker run`` command used to (re)create the container."""
    parts = [
        "docker run -d",
        f"--name {shlex.quote(settings.frigate_container_name)}",
        "--restart unless-stopped",
        "--stop-timeout 30",
        f"--mount {CACHE_TMPFS}",
        f"--shm-size={settings.frigate_shm_size}",
    ]
    if gpu == "vaapi":
        parts.append(f"--device {shlex.quote(GPU_DEVICE)}")
    parts += [
        f"-v {shlex.quote(config_dir)}:/config",
        f"-v {shlex.quote(storage_dir)}:/media/frigate",
        "-v /etc/localtime:/etc/localtime:ro",
        f"--env-file {shlex.quote(env_path)}",
        f"-p {shlex.quote(bind_address)}:{settings.frigate_ui_port}:{settings.frigate_ui_port}",
        shlex.quote(settings.frigate_image),
    ]
    return " ".join(parts)
