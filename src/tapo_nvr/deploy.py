"""Deploy or update the Frigate container on the NVR host."""

from __future__ import annotations

import shlex
import time

from .config import ConfigError, Settings, resolve_remote_base
from .frigate import GPU_DEVICE, docker_run_command, render_config, render_env
from .relay import resolve_relay_host
from .ssh import SSHClient
from .util import redact


def _resolve_gpu(ssh: SSHClient, requested: str) -> str:
    if requested != "auto":
        return requested
    if ssh.run(f"test -e {shlex.quote(GPU_DEVICE)}").ok:
        return "vaapi"
    return "none"


def _wait_until_running(ssh: SSHClient, name: str, attempts: int = 15, delay: float = 2.0) -> bool:
    probe = "docker inspect -f {{.State.Running}} " + shlex.quote(name)
    for _ in range(attempts):
        result = ssh.run(probe)
        if result.ok and result.output.strip() == "true":
            return True
        time.sleep(delay)
    return False


def deploy(
    settings: Settings,
    *,
    pull: bool = True,
    gpu: str | None = None,
    dry_run: bool = False,
) -> None:
    """Write the Frigate configuration and (re)create its container."""
    gpu_mode = (gpu or settings.frigate_gpu).lower()
    if not dry_run:
        settings.require_camera()
        settings.require_nvr()
    relay_host = resolve_relay_host(settings.relay_host)

    if dry_run:
        home = "/home/<nvr-user>"
        base = resolve_remote_base(home, settings.nvr_base_path)
        frigate_dir = f"{base}/frigate"
        config_dir = f"{frigate_dir}/config"
        storage_dir = settings.remote_storage_dir(home, base)
        env_path = f"{frigate_dir}/frigate.env"
        preview_gpu = "vaapi" if gpu_mode == "auto" else gpu_mode
        note = " (auto: the real run probes /dev/dri/renderD128)" if gpu_mode == "auto" else ""
        print(f"# GPU: {gpu_mode}{note}")
        print(f"# {config_dir}/config.yml")
        print(render_config(settings, preview_gpu), end="")
        print("\n# frigate.env (written with mode 0600)")
        print(f"FRIGATE_CAMERA_HOST={relay_host}")
        print("FRIGATE_CAMERA_USERNAME=<url-encoded CAMERA_USERNAME>")
        print("FRIGATE_CAMERA_PASSWORD=<url-encoded CAMERA_PASSWORD>")
        print("\n# container")
        print(
            docker_run_command(
                settings,
                gpu=preview_gpu,
                config_dir=config_dir,
                storage_dir=storage_dir,
                env_path=env_path,
                bind_address="<nvr-tailscale-address>",
            )
        )
        return

    with SSHClient(settings) as ssh:
        daemon = ssh.run("docker info")
        if not daemon.ok:
            raise ConfigError(
                "The Docker daemon is not reachable on the NVR host. Confirm Docker "
                "is running and that the NVR user can use it without sudo "
                "(for example, is in the 'docker' group)."
            )

        home = ssh.home()
        base = resolve_remote_base(home, settings.nvr_base_path)
        frigate_dir = f"{base}/frigate"
        config_dir = f"{frigate_dir}/config"
        config_path = f"{config_dir}/config.yml"
        storage_dir = settings.remote_storage_dir(home, base)
        env_path = f"{frigate_dir}/frigate.env"

        create_directories = (
            f"mkdir -p {shlex.quote(config_dir)} {shlex.quote(storage_dir)} "
            f"&& chmod 700 {shlex.quote(base)}"
        )
        ssh.run_ok(
            create_directories,
            "Could not create the Frigate directories",
        )

        gpu_mode = _resolve_gpu(ssh, gpu_mode)
        print(f"GPU acceleration: {gpu_mode}")

        ssh.put_file(config_path, render_config(settings, gpu_mode))
        ssh.put_file(env_path, render_env(settings, relay_host))
        print(f"Wrote {config_path} and {env_path}")

        if pull:
            print(f"Pulling {settings.frigate_image} (this may take a while)...")
            ssh.run_ok(
                f"docker pull {shlex.quote(settings.frigate_image)}",
                "Could not pull the Frigate image",
            )

        container = settings.frigate_container_name
        if ssh.run(f"docker inspect --type container {shlex.quote(container)}").ok:
            ssh.run_ok(
                f"docker rm -f {shlex.quote(container)}",
                "Could not remove the existing Frigate container",
            )

        nvr_address = ssh.run("tailscale ip -4 | head -1").output.strip()
        if not nvr_address:
            nvr_address = "127.0.0.1"
            print(
                "Warning: could not detect the NVR Tailscale address; binding the UI to localhost."
            )

        ssh.run_ok(
            docker_run_command(
                settings,
                gpu=gpu_mode,
                config_dir=config_dir,
                storage_dir=storage_dir,
                env_path=env_path,
                bind_address=nvr_address,
            ),
            "Could not start the Frigate container",
            timeout=120,
        )

        if not _wait_until_running(ssh, container):
            logs = ssh.run(f"docker logs --tail 50 {shlex.quote(container)}")
            message = redact(f"{logs.output}\n{logs.error}".strip())
            raise ConfigError(f"Frigate did not stay running. Recent logs:\n{message}")

        print(f"Frigate is running. UI: https://{nvr_address}:{settings.frigate_ui_port}")
        print(f"Recordings: {storage_dir}")
