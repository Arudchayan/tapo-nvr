# Architecture and threat model

Two deployment shapes are supported: the original relay + Frigate NVR, and the
no-NVR-host modes that use the camera's SD card or record the RTSP stream on the
laptop. The relay design is described first; the other modes follow.

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
streams, and half-closes the opposite direction when one side ends, so the
remaining direction can finish cleanly.

A deployment manages exactly one camera. Multiple cameras are out of scope for
now; run one relay per camera (each on its own port) if needed.

## SD-card backup mode

For installations without an always-on NVR host, `tapo-nvr sync` copies the
camera's own recordings to a folder:

```text
Camera (microSD, recording autonomously)
    |
    |  Tapo local API on the camera LAN
    v
Laptop: tapo-nvr sync -> SYNC_OUTPUT_DIR (for example a Google Drive folder)
```

The laptop can be switched off. The camera keeps recording until the card
wraps, and the next sync copies the missing clips. No relay, Tailscale, Docker,
or Frigate is involved. SD playback uses an unofficial local API through
`pytapo`; the camera firmware is not modified.

Tapo cameras allow only two of Tapo Care, microSD, and NVR/NAS recording to be
active at once. SD-card backup therefore coexists with Tapo Care or an NVR, but
not both.

## Laptop recording mode

`tapo-nvr record` makes the laptop the recorder:

```text
Camera RTSP -> ffmpeg on laptop -> local staging
                                      |
                                      v
                         publish folder (for example Google Drive)
                                      |
                                      +-> local segment deleted after RECORD_KEEP_HOURS
```

There is no camera-side buffer in this mode. Recording stops when the laptop
sleeps, shuts down, or loses the camera's network. Segments are 30 minutes by
default and are fragmented MP4, so an interrupted segment stays playable.

## Components

| Component | Where it runs | Purpose |
| --- | --- | --- |
| `tapo-nvr relay` | Relay host | Accepts TCP connections on the Tailscale address and forwards them to the camera. |
| `tapo-nvr deploy` | Relay host, over SSH | Renders `config.yml` and a mode-`0600` environment file, then recreates the Frigate container. |
| `tapo-nvr inspect` | Relay host (local and remote checks) | Verifies the camera, relay, Tailscale, container, and recent Frigate logs. |
| `tapo-nvr fetch-clip` | Relay host, over SFTP | Downloads the newest recording for inspection. |
| `tapo-nvr sync` | Laptop on the camera LAN | Copies new SD-card recordings to a local or cloud-synced folder. |
| `tapo-nvr record` | Laptop on the camera LAN | Records the RTSP stream continuously and publishes segments to a local or cloud-synced folder. |
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
