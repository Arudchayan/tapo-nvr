# Troubleshooting

## `error: Configuration file not found`

Commands look for `./.env` by default. Pass `--env /path/to/.env`, or run the
command from the directory that contains the file.

## `Invalid configuration line 1` or `Missing required setting(s)`

The `.env` file is malformed or missing keys.

- Save the file as UTF-8. A UTF-8 byte-order mark is fine; UTF-16 files are
  rejected with a specific error. On Windows, use "UTF-8" (not "UTF-16") in
  your editor, or `Set-Content -Encoding utf8` in PowerShell 7.
- Compare your file with `.env.example` and
  [docs/configuration.md](configuration.md).
- Unknown keys produce a warning such as
  `Ignoring unknown setting RELAY_ALLOWED_CIDRS`. Check the spelling.

## `Host key verification failed` or `SSH connection ... failed`

Strict host key checking is enabled by default. Add the NVR host key once:

```bash
ssh-keyscan -p <port> <nvr-host> >> ~/.ssh/known_hosts
```

Compare the fingerprint with the one printed by `ssh-keyscan` on the NVR host
before trusting it. For a throwaway test host you can set
`NVR_STRICT_HOST_KEY_CHECKING=false`, but never leave it off in production.

## `The Docker daemon is not reachable on the NVR host`

`tapo-nvr deploy` needs the SSH user to use Docker without `sudo`:

```bash
sudo usermod -aG docker $USER
# log out and back in, then verify:
docker info
```

## Relay does not start: `Could not determine this host's Tailscale IPv4 address`

- Confirm `tailscale status` works on the relay host.
- If the Tailscale CLI is not on `PATH`, set `RELAY_HOST` to the Tailscale IP
  explicitly in `.env`.
- At boot, Tailscale may not be ready yet. The relay retries every five
  seconds, so no action is usually needed.
- IPv6 bind addresses are not supported; use the Tailscale IPv4 address.

## `nothing is listening on port ...` after installing the Windows task

- Check `%ProgramData%\tapo-nvr\relay.log`.
- Confirm `PYTHON_PATH` points at the interpreter where `pip install .` was
  run; the installer prints the interpreter it selected.
- Run `deploy\windows\install-relay.ps1` from an elevated session; without it,
  the firewall rule is not created.
- Remove a leftover Startup shortcut to avoid two relay instances fighting for
  the port.

## The NVR cannot reach the relay

- From the NVR host: `nc -vz <relay-tailscale-ip> 8554`.
- Confirm both hosts are in the same tailnet and that Tailscale ACLs allow the
  connection. See [SECURITY.md](../SECURITY.md) for an example ACL.
- Confirm `RELAY_ALLOWED_CIDR` covers the NVR's address (the default,
  `100.64.0.0/10`, covers all Tailscale clients).
- `tapo-nvr inspect --scope local` shows the resolved listen address.

## Frigate starts but shows no frames

- Confirm the camera RTSP port is reachable from the relay host:
  `tapo-nvr inspect --scope local`.
- Confirm the credentials are the *Camera Account* credentials, not the Tapo
  cloud account.
- Check `tapo-nvr inspect --scope remote` for the `recent_logs` check.
- If your camera uses different stream paths or port, update
  `CAMERA_RECORD_STREAM`, `CAMERA_DETECT_STREAM`, and `CAMERA_RTSP_PORT`.
- If the camera password contains reserved characters such as `@`, `:`, or
  `/`, the generated RTSP URL percent-encodes it. Most cameras accept the
  encoded form, but some compare the raw string. If authentication fails only
  with such a password, set a camera account password without reserved
  characters.

## `Frigate did not stay running`

`tapo-nvr deploy` prints the last 50 log lines after a failed start. Common
causes:

- Invalid camera URL or unreachable relay.
- `detect` resolution does not match the sub stream, which makes Frigate exit
  with a resolution mismatch error. Update `CAMERA_DETECT_WIDTH`,
  `CAMERA_DETECT_HEIGHT`, and `CAMERA_DETECT_FPS`.
- The Frigate image requires a device that does not exist. Set
  `FRIGATE_GPU=none`.

`tapo-nvr deploy` removes the previous container before starting the new one,
so a failed start leaves no running container until you fix the configuration
and run `deploy` again. The configuration and recordings are retained.

## VAAPI errors such as `No usable VA-API devices found`

The NVR host has no usable `/dev/dri/renderD128`. Set `FRIGATE_GPU=none` and
redeploy, or pass the correct device and configure `ffmpeg.hwaccel_args`
manually. With the default `FRIGATE_GPU=auto`, `tapo-nvr inspect` reports the
GPU device as informational rather than failing.

## `Storage directory does not exist on the NVR host`

The default is `{NVR_BASE_PATH}/frigate/storage`, for example
`~/tapo-nvr/frigate/storage`. If you set `FRIGATE_STORAGE_PATH`, make sure the
directory exists on the NVR host; `tapo-nvr deploy` creates it.

## Recordings fill the disk

`RETENTION_DAYS` and `MOTION_RETENTION_DAYS` control Frigate's own retention.
Continuous recording is disabled by default. `tapo-nvr inspect` includes a
`storage` check with free space.

## `The sync command needs the optional 'pytapo' dependency`

Install the sync extra into the same environment as the CLI:

```bash
pip install 'tapo-nvr[sync]'
# or, from a checkout:
pip install '.[sync]'
```

## `The sync command requires Python 3.11 or newer`

The `pytapo` dependency uses `asyncio.timeout`, which arrived in Python 3.11.
Run `sync` from a newer interpreter (a separate virtual environment is fine);
the relay, deploy, inspect, and fetch-clip commands still work on Python 3.10.

## `Missing required executable(s): ffmpeg, ffprobe`

Install FFmpeg and make sure both executables are on `PATH`, then reopen the
terminal. On Windows, `winget install Gyan.FFmpeg` is usually enough. `sync`
uses FFmpeg to remux the camera's MPEG-TS stream into MP4.

## `Invalid authentication data` or error `-40211` during sync

`sync` needs the **Tapo cloud account password** in
`CAMERA_CLOUD_PASSWORD`, not the Camera Account password used for RTSP. The
camera account is still needed for Frigate; the two credentials are separate.

If the password is correct and the error persists, update the camera firmware
and upgrade `pytapo`. SD-card downloads rely on TP-Link's private local API,
which changes between firmware releases.

## `Video playback is not supported by this camera`

The camera did not expose its playback API. Check that:

- A microSD card is inserted, formatted, and visible in the Tapo app.
- **Storage & Recording → Local Recording** is enabled.
- The camera is on the same LAN as the laptop.
- You are using a supported model and a current firmware version.

## `record --check` returns `401 Unauthorized`

RTSP rejected `CAMERA_USERNAME` / `CAMERA_PASSWORD`. These are normally the
Camera Account from the Tapo app, not the TP-Link cloud account. Some firmware
also accepts the cloud account; if the Camera Account is not set up, create it
under **Advanced Settings → Camera Account** in the Tapo app.

## `record` stops when the laptop sleeps or the lid closes

This is expected: the laptop is the recorder and the camera has no buffer in
this mode. Plug the laptop in, set sleep to **Never**, set the lid-close action
to **Do nothing**, and start `tapo-nvr record` at logon.

## `Output sentinel ... is missing`

The recorder requires `RECORD_OUTPUT_DIR\.tapo-nvr-output` to prove the output
folder is the real mounted destination. If Google Drive is not mounted, the
recorder will not create the folder or publish into a local shadow. Mount Drive,
then create the sentinel once:

```powershell
New-Item -ItemType File "G:\My Drive\TapoNVR\record\.tapo-nvr-output" -Force
```

Segments stay in staging until the sentinel and output path are back.

## `could not publish ...` in the record log

The publish directory is unreachable or read-only (for example Google Drive is
not mounted, or the Drive client is offline). The segment stays in
`RECORD_STAGING_DIR` and is retried every 30 seconds; nothing is deleted until a
published copy with the same size exists. Remount Drive or fix the path and the
recorder catches up.

## The record staging disk fills up

A 2K stream is roughly 28–40 GB/day. Lower `RECORD_KEEP_HOURS`, point
`RECORD_STAGING_DIR` at a larger local disk, or set
`CAMERA_RECORD_STREAM=stream2` to record the smaller substream. If the *Drive*
side is filling up, set `RECORD_OUTPUT_KEEP_DAYS` (for example `7`); the default
`0` keeps published files forever.

## `ffmpeg exited` repeatedly in the record log

- Confirm `record --check` succeeds.
- Close the Tapo app's live view and any other RTSP client; the camera allows a
  small number of simultaneous streams.
- Check that the camera is still on the same Wi-Fi/LAN and has a stable
  connection.

## `STORAGE_NOT_EXIST` or error `-71114`

The camera has no usable SD card mounted. In the Tapo app, open **Device
Settings → Storage & Recording** and check the card status. A healthy card
shows capacity and an online/normal status. If it shows offline, reseat the
card, format it in the app, or replace it. `sync` cannot download anything until
the card is mounted; detection/continuous recording can be enabled but has
nowhere to write.

## `No recordings` for a date that has footage

- The Tapo app's timeline and `sync` use the camera's local date. Check the
  date range with `--date YYYY-MM-DD` or widen it with `--since`.
- Detection recording only stores clips around events. If the schedule was
  off, there is nothing to download.
- Continuous recording produces many short segments; a busy day can take a
  while to copy.

## `Recording in progress` / `Camera busy`

The newest clip is still being written, so `sync` leaves it for the next run.
`Camera busy` usually means the Tapo app (or another client) is holding a
stream slot. Close live view and retry. The camera supports a small number of
simultaneous streams.

## Files are in the Google Drive folder but not uploaded yet

`sync` only writes files; Google Drive for Desktop performs the upload. Keep
Drive running and wait for it to finish before shutting the laptop. Check the
Drive tray icon for pending uploads, and make sure the destination is inside
the Drive mount rather than a local folder that looks similar.
