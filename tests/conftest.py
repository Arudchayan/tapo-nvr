"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from tapo_nvr.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        camera_host="camera.local",
        camera_username="camera-user",
        camera_password="p@ss:w/rd",
        relay_host="relay.example.ts.net",
        relay_port=8554,
        nvr_host="nvr.example.ts.net",
        nvr_ssh_user="nvr-admin",
        nvr_ssh_password="secret",
    )
