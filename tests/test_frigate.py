"""Tests for Frigate configuration and container rendering."""

from __future__ import annotations

from tapo_nvr.config import Settings
from tapo_nvr.frigate import docker_run_command, render_config, render_env


def test_render_config_uses_relay_and_placeholders(settings: Settings) -> None:
    config = render_config(settings, "vaapi")

    assert "preset-vaapi" in config
    assert f"{settings.frigate_camera_name}:" in config
    assert "{FRIGATE_CAMERA_HOST}:8554/stream1" in config
    assert "{FRIGATE_CAMERA_HOST}:8554/stream2" in config
    assert "days: 30" in config
    assert "days: 3" in config
    assert "rtsp://camera-user" not in config
    assert "p@ss" not in config


def test_render_config_without_hardware_acceleration(settings: Settings) -> None:
    config = render_config(settings, "none")

    assert "hwaccel" not in config
    assert "detectors:" in config


def test_render_config_uses_frigate_record_schema(settings: Settings) -> None:
    config = render_config(settings, "none")

    assert "  continuous:\n    days: 0" in config
    assert "  motion:\n    days: 3" in config
    assert "  alerts:\n    retain:\n      days: 30" in config
    assert "  detections:\n    retain:\n      days: 30" in config


def test_render_config_lists_tracked_objects() -> None:
    settings = Settings(camera_objects=("person", "dog"))
    config = render_config(settings, "none")

    assert "        - person" in config
    assert "        - dog" in config


def test_render_env_url_encodes_credentials(settings: Settings) -> None:
    env = render_env(settings, "relay.example.ts.net")

    assert "FRIGATE_CAMERA_HOST=relay.example.ts.net" in env
    assert "FRIGATE_CAMERA_USERNAME=camera-user" in env
    assert "FRIGATE_CAMERA_PASSWORD=p%40ss%3Aw%2Frd" in env


def test_docker_run_command_includes_gpu_and_private_binding(settings: Settings) -> None:
    command = docker_run_command(
        settings,
        gpu="vaapi",
        config_dir="/home/nvr/tapo-nvr/config",
        storage_dir="/home/nvr/tapo-nvr/storage",
        env_path="/home/nvr/tapo-nvr/frigate.env",
        bind_address="100.64.0.5",
    )

    assert command.startswith("docker run -d")
    assert "--device /dev/dri/renderD128" in command
    assert "-p 100.64.0.5:8971:8971" in command
    assert "--env-file /home/nvr/tapo-nvr/frigate.env" in command
    assert "-v /home/nvr/tapo-nvr/config:/config" in command
    assert "ghcr.io/blakeblackshear/frigate:stable" in command


def test_docker_run_command_without_gpu(settings: Settings) -> None:
    command = docker_run_command(
        settings,
        gpu="none",
        config_dir="/home/nvr/tapo-nvr/config",
        storage_dir="/home/nvr/tapo-nvr/storage",
        env_path="/home/nvr/tapo-nvr/frigate.env",
        bind_address="100.64.0.5",
    )

    assert "--device" not in command


def test_docker_run_command_quotes_paths_and_names() -> None:
    settings = Settings(
        frigate_container_name="tapo-frigate",
        frigate_storage_path="/media/my recordings",
    )
    command = docker_run_command(
        settings,
        gpu="none",
        config_dir="/home/nvr/tapo-nvr/config",
        storage_dir="/media/my recordings",
        env_path="/home/nvr/tapo-nvr/frigate.env",
        bind_address="100.64.0.5",
    )

    assert "'/media/my recordings':/media/frigate" in command
