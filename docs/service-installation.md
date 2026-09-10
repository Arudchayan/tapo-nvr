# Installing the relay as a service

The `tapo-nvr relay` command stays in the foreground and never daemonizes.
Use one of the options below so it starts automatically.

Install the package for the interpreter that will run the service first:

```bash
python -m pip install .
```

## Windows: boot-time scheduled task (recommended)

Requires an elevated PowerShell session. The script:

1. Reads `.env` (or `-EnvFile PATH`).
2. Adds an inbound firewall rule for the relay port, limited to
   `RELAY_ALLOWED_CIDR`.
3. Registers the `tapo-nvr relay` scheduled task to start at boot as `SYSTEM`.
4. Starts the task and verifies that the port is listening.

```powershell
cd deploy\windows
.\install-relay.ps1
```

Logs are written to `%ProgramData%\tapo-nvr\relay.log`.

To remove the task, rule, and shortcut:

```powershell
.\uninstall-relay.ps1
```

## Windows: user Startup shortcut (no admin rights)

Use this when you cannot elevate. The relay starts after the user logs in, so
the camera is unavailable while the user is signed out. The Windows firewall
may also need a manual inbound rule; the script prints a warning with the port.

```powershell
cd deploy\windows
.\install-relay-user-startup.ps1
```

Logs are written to `%LOCALAPPDATA%\tapo-nvr\relay.log`.

## Linux: systemd

```bash
sudo install -D -m 0644 deploy/systemd/tapo-nvr-relay.service /etc/systemd/system/tapo-nvr-relay.service
sudo install -D -m 0644 deploy/systemd/relay.env.example /etc/tapo-nvr/relay.env
sudo editor /etc/tapo-nvr/relay.env   # set CAMERA_HOST
sudo systemctl daemon-reload
sudo systemctl enable --now tapo-nvr-relay
sudo journalctl -u tapo-nvr-relay -f
```

The unit runs as a `DynamicUser` with an empty capability set and a read-only
system, and it only needs to reach the camera and bind an unprivileged port.
`RELAY_HOST=auto` resolves the Tailscale address at start; restart the unit if
the address changes.

## Verify the relay

From the NVR host:

```bash
nc -vz <relay-tailscale-address> 8554
```

Or run `tapo-nvr inspect`, which performs this check and more.
