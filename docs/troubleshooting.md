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
