# tapo-nvr

[![CI](https://github.com/Arudchayan/tapo-nvr/actions/workflows/ci.yml/badge.svg)](https://github.com/Arudchayan/tapo-nvr/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

`tapo-nvr` connects a self-hosted [Frigate](https://frigate.video/) NVR to a
camera that lives on a different network. A small TCP relay runs next to the
camera and exposes **only the camera's RTSP port** on that host's
[Tailscale](https://tailscale.com/) address, so the camera's LAN is never
routable from the tailnet.

It was originally built for a TP-Link Tapo C220, but the relay is
camera-agnostic: any RTSP source works.

## Why a relay instead of a subnet route?

Advertising a camera subnet route means every device on your tailnet can reach
every device on the camera LAN, usually including the camera's web UI and ONVIF
endpoints. A relay narrows the exposure to a single TCP port and lets Tailscale
ACLs be the only access control layer. See
[docs/architecture.md](docs/architecture.md) for the full design.

## Architecture

```mermaid
flowchart LR
    subgraph CameraLAN["Camera LAN"]
        Camera["RTSP camera<br/>192.168.x.x:554"]
        Relay["tapo-nvr relay<br/>Tailscale IP:8554"]
        Camera -- "RTSP" --> Relay
    end
    subgraph NVR["NVR host"]
        Frigate["Frigate container<br/>Tailscale IP:8971"]
    end
    Relay -- "Tailscale (CGNAT)" --> Frigate
```

- **Relay host** runs `tapo-nvr relay` plus Tailscale. It does not need router
  access, port forwarding, or IP forwarding.
- **NVR host** runs Tailscale and the Frigate Docker container. `tapo-nvr`
  manages the container over SSH from the relay host.

## Requirements

Relay host:

- Python 3.10 or newer
- Tailscale
- Same LAN as the camera

NVR host:

- Docker Engine with the `docker` CLI available over SSH
- Tailscale
- Optional: `/dev/dri/renderD128` for VAAPI hardware acceleration

The management commands run from the relay host and reach the NVR host over
SSH. Key authentication is supported and preferred.

## Quick start

### 1. Install

```bash
git clone https://github.com/Arudchayan/tapo-nvr.git
cd tapo-nvr
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install .
```

Or install it as an isolated CLI with [pipx](https://pipx.pypa.io/):

```bash
pipx install .
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set the camera address and credentials, a Tailscale-reachable
NVR host, and SSH details. Every setting is documented in
[docs/configuration.md](docs/configuration.md).

### 3. Start the relay on the relay host

```bash
# Foreground, for a quick test
tapo-nvr relay --target 192.168.1.50

# Windows: boot-time task + firewall rule (elevated PowerShell)
deploy\windows\install-relay.ps1

# Windows: no-admin fallback
deploy\windows\install-relay-user-startup.ps1

# Linux: systemd unit
sudo install -D -m 0644 deploy/systemd/tapo-nvr-relay.service /etc/systemd/system/tapo-nvr-relay.service
sudo install -D -m 0644 deploy/systemd/relay.env.example /etc/tapo-nvr/relay.env
sudo systemctl enable --now tapo-nvr-relay
```

### 4. Deploy Frigate on the NVR host

```bash
# Preview the generated configuration and container command first
tapo-nvr deploy --dry-run

# Write the configuration and (re)create the container over SSH
tapo-nvr deploy
```

### 5. Verify

```bash
tapo-nvr inspect          # checks relay host and NVR host
tapo-nvr fetch-clip       # downloads the newest recording
```

## Commands

| Command | Description |
| --- | --- |
| `tapo-nvr deploy` | Render the Frigate config, write it over SSH, and (re)create the container. Use `--dry-run` to preview and `--no-pull` to skip `docker pull`. |
| `tapo-nvr inspect` | JSON health checks for the camera, relay, Tailscale, container, image, and recent Frigate logs. `--scope local` or `--scope remote` narrows the checks. |
| `tapo-nvr fetch-clip` | Download the most recent MP4 from the NVR storage directory. |
| `tapo-nvr relay` | Run the camera-only TCP relay. See `tapo-nvr relay --help`. |

All commands accept `--env PATH` to point at a different environment file.

## Security model

- The relay binds to a local address and, by default, accepts clients only from
  `100.64.0.0/10` (the Tailscale CGNAT range) and only forwards a single TCP
  port to the camera.
- Camera credentials are transferred over SSH and written to a mode `0600`
  environment file on the NVR host. They never appear in the Frigate YAML,
  which references them through `{FRIGATE_*}` placeholders.
- SSH host keys are verified by default (`NVR_STRICT_HOST_KEY_CHECKING=true`).
- No router ports are opened and no camera subnet route is advertised.

See [SECURITY.md](SECURITY.md) for the threat model and reporting process.

## Documentation

- [Configuration reference](docs/configuration.md)
- [Architecture and threat model](docs/architecture.md)
- [Installing the relay as a service](docs/service-installation.md)
- [Troubleshooting](docs/troubleshooting.md)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)
