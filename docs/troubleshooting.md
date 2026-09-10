# Troubleshooting

## `Host key verification failed` or `SSH connection ... failed`

Strict host key checking is enabled by default. Add the NVR host key once:

```bash
ssh-keyscan -p <port> <nvr-host> >> ~/.ssh/known_hosts
```

Compare the fingerprint with the one printed by `ssh-keyscan` on the NVR host
before trusting it. For a throwaway test host you can set
`NVR_STRICT_HOST_KEY_CHECKING=false`, but never leave it off in production.

## `Missing required setting(s): ...`

The `.env` file is missing keys. Compare it with `.env.example` and
[docs/configuration.md](configuration.md). Use `--env PATH` if the file is not
in the current directory.

## Relay does not start: `Could not determine this host's Tailscale IPv4 address`

- Confirm `tailscale status` works on the relay host.
- If the Tailscale CLI is not on `PATH`, set `RELAY_HOST` to the Tailscale IP
  explicitly in `.env`.
- At boot, Tailscale may not be ready yet. The relay retries every five
  seconds, so no action is usually needed.

## `nothing is listening on port ...` after installing the Windows task

- Check `%ProgramData%\tapo-nvr\relay.log`.
- Confirm the package is installed for the interpreter in `PYTHON_PATH`.
- Run `deploy\windows\install-relay.ps1` from an elevated session; without it,
  the firewall rule is not created.

## The NVR cannot reach the relay

- From the NVR host: `nc -vz <relay-tailscale-ip> 8554`.
- Confirm the relay host and NVR host are in the same tailnet and that
  Tailscale ACLs allow the connection.
- Confirm the relay listen address is the Tailscale address, not `127.0.0.1`.
  `tapo-nvr inspect --scope local` shows the resolved address.

## Frigate starts but shows no frames

- Confirm the camera RTSP port is reachable from the relay host:
  `tapo-nvr inspect --scope local`.
- Confirm the credentials are the *Camera Account* credentials, not the Tapo
  cloud account.
- Check `tapo-nvr inspect --scope remote` for the `recent_logs` check.
- If your camera uses different stream paths or port, update
  `CAMERA_RECORD_STREAM`, `CAMERA_DETECT_STREAM`, and `CAMERA_RTSP_PORT`.

## `Frigate did not stay running`

`tapo-nvr deploy` prints the last 50 log lines after a failed start. Common
causes:

- Invalid camera URL or unreachable relay.
- `detect` resolution does not match the sub stream, which makes Frigate exit
  with a resolution mismatch error. Update `CAMERA_DETECT_WIDTH`,
  `CAMERA_DETECT_HEIGHT`, and `CAMERA_DETECT_FPS`.
- The Frigate image requires a device that does not exist. Set
  `FRIGATE_GPU=none`.

## VAAPI errors such as `No usable VA-API devices found`

The NVR host has no usable `/dev/dri/renderD128`. Set `FRIGATE_GPU=none` and
redeploy, or pass the correct device and configure `ffmpeg.hwaccel_args`
manually.

## Recordings fill the disk

`RETENTION_DAYS` and `MOTION_RETENTION_DAYS` control Frigate's own retention.
Continuous recording is disabled by default. `tapo-nvr inspect` includes a
`storage` check with free space.

## `error: Configuration file not found`

Commands look for `./.env` by default. Pass `--env /path/to/.env`, or run the
command from the directory that contains the file.
