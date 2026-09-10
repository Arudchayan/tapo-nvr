"""Tests for configuration parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tapo_nvr.config import (
    DEFAULT_FRIGATE_IMAGE,
    ConfigError,
    Settings,
    load_env_file,
    parse_dotenv,
    parse_networks,
    resolve_remote_base,
)


def test_parse_dotenv_handles_comments_quotes_and_whitespace() -> None:
    text = """
    # A comment

    CAMERA_HOST=192.168.1.10
    CAMERA_PASSWORD="p@ss # not a comment"
    RELAY_HOST=auto # trailing comment
    NVR_BASE_PATH=~/tapo-nvr
    """

    values = parse_dotenv(text)

    assert values["CAMERA_HOST"] == "192.168.1.10"
    assert values["CAMERA_PASSWORD"] == "p@ss # not a comment"
    assert values["RELAY_HOST"] == "auto"
    assert values["NVR_BASE_PATH"] == "~/tapo-nvr"


def test_parse_dotenv_supports_export_prefix() -> None:
    assert parse_dotenv("export CAMERA_HOST=192.168.1.10") == {"CAMERA_HOST": "192.168.1.10"}


def test_parse_dotenv_keeps_equals_signs_in_values() -> None:
    values = parse_dotenv("CAMERA_PASSWORD=a=b=c")
    assert values["CAMERA_PASSWORD"] == "a=b=c"


def test_parse_dotenv_rejects_malformed_lines() -> None:
    with pytest.raises(ConfigError):
        parse_dotenv("this line has no equals sign")


def test_parse_dotenv_rejects_unterminated_quotes() -> None:
    with pytest.raises(ConfigError):
        parse_dotenv('CAMERA_PASSWORD="unterminated')


def test_load_env_file_strips_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("\ufeffCAMERA_HOST=192.168.1.10\n", encoding="utf-8")

    assert load_env_file(path)["CAMERA_HOST"] == "192.168.1.10"


def test_load_env_file_rejects_utf16(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes("CAMERA_HOST=192.168.1.10\n".encode("utf-16"))

    with pytest.raises(ConfigError):
        load_env_file(path)


def test_from_mapping_applies_defaults_and_overrides() -> None:
    settings = Settings.from_mapping(
        {
            "FRIGATE_UI_PORT": "9000",
            "NVR_STRICT_HOST_KEY_CHECKING": "false",
            "CAMERA_OBJECTS": "person, dog",
        }
    )

    assert settings.frigate_ui_port == 9000
    assert settings.nvr_strict_host_key_checking is False
    assert settings.camera_objects == ("person", "dog")
    assert settings.relay_port == 8554


def test_from_mapping_treats_blank_values_as_unset() -> None:
    settings = Settings.from_mapping({"FRIGATE_IMAGE": "   "})

    assert settings.frigate_image == DEFAULT_FRIGATE_IMAGE


def test_from_mapping_preserves_quoted_password_whitespace() -> None:
    settings = Settings.from_mapping(parse_dotenv('CAMERA_PASSWORD=" secret "'))

    assert settings.camera_password == " secret "


def test_from_mapping_warns_about_unknown_keys(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        Settings.from_mapping({"RELAY_ALLOWED_CIDRS": "100.64.0.0/10"})

    assert "RELAY_ALLOWED_CIDRS" in caplog.text


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("RELAY_PORT", "not-a-port"),
        ("RELAY_PORT", "70000"),
        ("FRIGATE_GPU", "cuda"),
        ("RELAY_ALLOWED_CIDR", "not-a-cidr"),
        ("FRIGATE_CAMERA_NAME", "bad name!"),
        ("FRIGATE_CONTAINER_NAME", "-bad"),
        ("FRIGATE_SHM_SIZE", "lots"),
        ("NVR_STRICT_HOST_KEY_CHECKING", "maybe"),
        ("CAMERA_OBJECTS", ","),
    ],
)
def test_from_mapping_rejects_invalid_values(key: str, value: str) -> None:
    with pytest.raises(ConfigError):
        Settings.from_mapping({key: value})


def test_require_camera_lists_missing_keys() -> None:
    with pytest.raises(ConfigError) as excinfo:
        Settings().require_camera()

    message = str(excinfo.value)
    assert "CAMERA_HOST" in message
    assert "CAMERA_USERNAME" in message
    assert "CAMERA_PASSWORD" in message


def test_require_nvr_needs_an_authentication_method() -> None:
    settings = Settings(nvr_host="nvr", nvr_ssh_user="admin")

    with pytest.raises(ConfigError):
        settings.require_nvr()

    Settings(nvr_host="nvr", nvr_ssh_user="admin", nvr_ssh_password="secret").require_nvr()
    Settings(nvr_host="nvr", nvr_ssh_user="admin", nvr_ssh_key="~/.ssh/id").require_nvr()


def test_resolve_remote_base() -> None:
    assert resolve_remote_base("/home/nvr", "~/tapo-nvr") == "/home/nvr/tapo-nvr"
    assert resolve_remote_base("/home/nvr", "/srv/media") == "/srv/media"

    for invalid in ("relative/path", "~other/path", "~/", "/"):
        with pytest.raises(ConfigError):
            resolve_remote_base("/home/nvr", invalid)


def test_parse_networks_normalizes_and_defaults() -> None:
    networks = parse_networks(["100.64.0.1/10, 127.0.0.1"])
    assert [str(network) for network in networks] == ["100.64.0.0/10", "127.0.0.1/32"]
    assert [str(network) for network in parse_networks([])] == ["100.64.0.0/10"]


def test_remote_storage_dir_honours_override() -> None:
    settings = Settings(frigate_storage_path="~/recordings")

    assert settings.remote_storage_dir("/home/nvr", "/home/nvr/tapo-nvr") == (
        "/home/nvr/recordings"
    )
    assert Settings().remote_storage_dir("/home/nvr", "/home/nvr/tapo-nvr") == (
        "/home/nvr/tapo-nvr/frigate/storage"
    )
