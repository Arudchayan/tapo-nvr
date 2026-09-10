# Configuration reference

Copy `.env.example` to `.env` and adjust the values. The file is read from the
current working directory by default; use `--env PATH` with any command to
point somewhere else.

Parser notes:

- Lines starting with `#` are comments, and blank lines are ignored.
- Values may be wrapped in single or double quotes.
- An unquoted ` #` starts a trailing comment.
- Values are never interpolated.

## Camera

| Key | Default | Description |
| --- | --- | --- |
| `CAMERA_HOST` | *(required)* | Camera host name or IP address. The relay host must be able to reach it. |
| `CAMERA_RTSP_PORT` | `554` | Camera RTSP port. |
| `CAMERA_USERNAME` | *(required)* | Camera account user name. For Tapo cameras this is the separate *Camera Account*, not the TP-Link cloud account. |
| `CAMERA_PASSWORD` | *(required)* | Camera account password. |
| `CAMERA_RECORD_STREAM` | `stream1` | Main RTSP stream used for recording. |
| `CAMERA_DETECT_STREAM` | `stream2` | Sub stream used for detection. Use a lower-resolution stream when available. |
| `CAMERA_DETECT_WIDTH` | `640` | Detection width reported to Frigate. Must match the sub stream. |
| `CAMERA_DETECT_HEIGHT` | `360` | Detection height reported to Frigate. Must match the sub stream. |
| `CAMERA_DETECT_FPS` | `5` | Detection frames per second. |
| `CAMERA_OBJECTS` | `person,cat,dog` | Comma-separated object labels Frigate tracks. |

## Relay

| Key | Default | Description |
| --- | --- | --- |
| `RELAY_HOST` | `auto` | Local address the relay listens on. `auto` resolves the Tailscale IPv4 address with `tailscale ip -4`. Set an explicit IP if the CLI is unavailable. |
| `RELAY_PORT` | `8554` | Port exposed on the Tailscale address. It only needs to be reachable from the NVR host. |
| `RELAY_ALLOWED_CIDR` | `100.64.0.0/10` | Comma-separated CIDR ranges whose clients may connect, in addition to the firewall rule created by the Windows installer. Set to `0.0.0.0/0` only if you enforce access with Tailscale ACLs. |

## NVR host

| Key | Default | Description |
| --- | --- | --- |
| `NVR_HOST` | *(required)* | Tailscale host name or IP address of the NVR host. |
| `NVR_SSH_PORT` | `22` | SSH port. |
| `NVR_SSH_USER` | *(required)* | SSH user on the NVR host. |
| `NVR_SSH_KEY` | *(empty)* | Path to a private key. Takes precedence over `NVR_SSH_PASSWORD`. |
| `NVR_SSH_PASSWORD` | *(empty)* | Password used when no key is configured. Keep it out of shell history. |
| `NVR_STRICT_HOST_KEY_CHECKING` | `true` | Reject unknown SSH host keys. Set to `false` only for initial setup or throwaway hosts. |
| `NVR_BASE_PATH` | `~/tapo-nvr` | Remote directory for the configuration and recordings. An absolute path or a path starting with `~`. |

The first connection with strict host key checking requires an entry in
`known_hosts`. Add it once with:

```bash
ssh-keyscan -p 22 nvr-host.your-tailnet.ts.net >> ~/.ssh/known_hosts
```

Verify the fingerprint out-of-band before trusting it.

## Frigate

| Key | Default | Description |
| --- | --- | --- |
| `FRIGATE_CAMERA_NAME` | `tapo_c220` | Camera key in the Frigate configuration. Letters, digits and underscores only. |
| `FRIGATE_CONTAINER_NAME` | `tapo-frigate` | Docker container name managed by this tool. |
| `FRIGATE_IMAGE` | `ghcr.io/blakeblackshear/frigate:stable` | Frigate image. Pin a version tag for reproducible upgrades. |
| `FRIGATE_UI_PORT` | `8971` | Frigate authenticated UI/API port, bound to the NVR's Tailscale address only. |
| `FRIGATE_GPU` | `auto` | `auto` enables VAAPI when `/dev/dri/renderD128` exists on the NVR host, otherwise no hardware acceleration. Also accepts `vaapi` and `none`. |
| `FRIGATE_SHM_SIZE` | `64m` | Docker `--shm-size`. Increase it for multiple cameras or higher-resolution detection. |
| `FRIGATE_STORAGE_PATH` | *(empty)* | Remote recordings directory. Empty means `$NVR_BASE_PATH/frigate/storage`. |
| `RETENTION_DAYS` | `30` | Retention for alerts, detections, and snapshots. |
| `MOTION_RETENTION_DAYS` | `3` | Retention for motion-only recording segments. Continuous recording is disabled. |

## Windows service scripts

| Key | Default | Description |
| --- | --- | --- |
| `PYTHON_PATH` | *(empty)* | Python interpreter used by the relay scheduled task or Startup shortcut. Defaults to `python.exe` on `PATH`. |
