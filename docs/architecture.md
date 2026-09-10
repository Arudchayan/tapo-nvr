# Architecture and threat model

## Data flow

```text
Camera (RTSP :554)
    |
    |  plain RTSP on the camera LAN
    v
Relay host: tapo-nvr relay (Tailscale IP :8554)
    |
    |  Tailscale WireGuard tunnel
    v
NVR host: Frigate -> ~/tapo-nvr/frigate/storage (/media/frigate)
```

The relay is a transparent TCP proxy. It does not parse RTSP, does not store
streams, and terminates a connection as soon as either side closes.

## Components

| Component | Where it runs | Purpose |
| --- | --- | --- |
| `tapo-nvr relay` | Relay host | Accepts TCP connections on the Tailscale address and forwards them to the camera. |
| `tapo-nvr deploy` | Relay host, over SSH | Renders `config.yml` and a mode-`0600` environment file, then recreates the Frigate container. |
| `tapo-nvr inspect` | Relay host (local and remote checks) | Verifies the camera, relay, Tailscale, container, and recent Frigate logs. |
| `tapo-nvr fetch-clip` | Relay host, over SFTP | Downloads the newest recording for inspection. |
| Windows scripts | Relay host | Install the relay as a boot-time task or a user Startup shortcut, including the firewall rule. |
| systemd unit | Relay host | Runs the relay as a hardened, unprivileged system service. |

## Why not a subnet route?

Tailscale subnet routing is the obvious way to connect an NVR to a camera on
another LAN. It also exposes the entire camera subnet to every authorized
tailnet node, including the camera's web UI, ONVIF endpoint, and any other
device on that LAN. A relay exposes exactly one port, bound to one address,
with an explicit allow list.

## Threat model

In scope:

- Preventing the camera LAN from becoming routable to the tailnet.
- Keeping camera credentials out of the Frigate configuration, logs, and
  version control.
- Not exposing the camera or the Frigate container beyond the Tailscale
  interface.

Out of scope:

- A compromised relay host or NVR host.
- A compromised Tailscale account or malicious tailnet peer. Tailscale ACLs are
  the access control layer; tags and ACLs can restrict which nodes may reach
  the relay port.
- Physical access to either host.

## Credential handling

1. `CAMERA_USERNAME` and `CAMERA_PASSWORD` live in `.env` on the relay host
   (Git-ignored).
2. `tapo-nvr deploy` URL-encodes them and writes `frigate.env` on the NVR host
   with mode `0600` over SFTP.
3. The Frigate `config.yml` contains only `{FRIGATE_CAMERA_USERNAME}` and
   `{FRIGATE_CAMERA_PASSWORD}` placeholders; Frigate substitutes the values at
   container start.
4. `tapo-nvr inspect` redacts `rtsp://user:password@` sequences from any output
   it prints.
