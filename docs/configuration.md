# Configuration reference

Copy `.env.example` to `.env` and adjust the values. Commands read `./.env` by
default; use `--env PATH` to point somewhere else.

Parser notes:

- Lines starting with `#` are comments, blank lines are ignored, and a leading
  `export ` is accepted.
- Values may be wrapped in single or double quotes; quoted values keep inner
  spaces. Values are never interpolated.
- An unquoted ` #` starts a trailing comment.
- Duplicate keys are last-wins.
- Files must be UTF-8. A UTF-8 byte-order mark is accepted; UTF-16/UTF-32 files
  are rejected with an explanatory error.
- Unknown keys are ignored with a warning in the command output, which catches
  typos such as `RELAY_ALLOWED_CIDRS`.

Keep `.env` readable only by your user (`chmod 600 .env` on POSIX, or the
equivalent `icacls` restriction on Windows): it contains the camera and SSH
passwords.

## Camera

| Key | Default | Description |
| --- | --- | --- |
| `CAMERA_HOST` | *(required)* | Camera host name or IP address. The relay host must be able to reach it. |
| `CAMERA_RTSP_PORT` | `554` | Camera RTSP port. |
| `CAMERA_USERNAME` | *(required)* | Camera account user name. For Tapo cameras this is the separate *Camera Account* created in the Tapo app, not the TP-Link cloud account. |
| `CAMERA_PASSWORD` | *(required)* | Camera account password. |
| `CAMERA_RECORD_STREAM` | `stream1` | Main RTSP stream used for recording. |
| `CAMERA_DETECT_STREAM` | `stream2` | Sub stream used for detection. Use a lower-resolution stream when available. |
| `CAMERA_DETECT_WIDTH` | `640` | Detection width reported to Frigate. Must match the sub stream. |
| `CAMERA_DETECT_HEIGHT` | `360` | Detection height reported to Frigate. Must match the sub stream. |
| `CAMERA_DETECT_FPS` | `5` | Detection frames per second. |
| `CAMERA_OBJECTS` | `person,cat,dog` | Comma-separated object labels Frigate tracks. |

## Relay

`tapo-nvr relay` reads these keys from `.env` by default; command-line flags
override each value individually.

| Key | Default | Description |
| --- | --- | --- |
| `RELAY_HOST` | `auto` | Local address the relay listens on. `auto` resolves the Tailscale IPv4 address with `tailscale ip -4`. Set an explicit IPv4 address if the CLI is unavailable. IPv6 bind addresses are not supported yet. |
| `RELAY_PORT` | `8554` | Port exposed on the Tailscale address. It only needs to be reachable from the NVR host. |
| `RELAY_ALLOWED_CIDR` | `100.64.0.0/10` | Comma-separated CIDR ranges whose clients may connect. The Windows installer also builds its firewall rule from this value. Only set it to `0.0.0.0/0` while `RELAY_HOST` remains the Tailscale address (the default) and your tailnet ACLs restrict access; never combine it with a public bind address. |

## NVR host

| Key | Default | Description |
| --- | --- | --- |
| `NVR_HOST` | *(required)* | Tailscale host name or IP address of the NVR host. |
| `NVR_SSH_PORT` | `22` | SSH port. |
| `NVR_SSH_USER` | *(required)* | SSH user on the NVR host. This user must be able to run `docker` without `sudo`. |
| `NVR_SSH_KEY` | *(empty)* | Path to a private key. Takes precedence over `NVR_SSH_PASSWORD`. |
| `NVR_SSH_PASSWORD` | *(empty)* | Password used when no key is configured. |
| `NVR_STRICT_HOST_KEY_CHECKING` | `true` | Reject unknown SSH host keys. Set to `false` only for initial setup or throwaway hosts. |
| `NVR_BASE_PATH` | `~/tapo-nvr` | Remote directory for the configuration and recordings. Must be an absolute path or start with `~/`; it cannot be the home directory or `/`. The layout is `{NVR_BASE_PATH}/frigate/{config,storage,frigate.env}`. |

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
| `FRIGATE_SHM_SIZE` | `64m` | Docker `--shm-size`. Increase it for higher-resolution detection or several simultaneous streams. |
| `FRIGATE_STORAGE_PATH` | *(empty)* | Remote recordings directory. Empty means `$NVR_BASE_PATH/frigate/storage`. |
| `RETENTION_DAYS` | `30` | Retention for alerts, detections, and snapshots. |
| `MOTION_RETENTION_DAYS` | `3` | Retention for motion-only recording segments. Continuous recording is disabled. |

## Windows service scripts

| Key | Default | Description |
| --- | --- | --- |
| `PYTHON_PATH` | *(empty)* | Python interpreter used by the relay scheduled task or Startup shortcut. Defaults to `python.exe` on `PATH`. Point it at your virtual environment's interpreter (for example `.venv\Scripts\python.exe`) when you installed the package there. |
