# Installing the relay as a service

The `tapo-nvr relay` command stays in the foreground and never daemonizes.
Use one of the options below so it starts automatically. In every case the
interpreter that runs the service must be able to `import tapo_nvr`.

## Windows: boot-time scheduled task (recommended)

Requires an elevated PowerShell session. The script:

1. Reads `.env` (or `-EnvFile PATH`).
2. Adds an inbound firewall rule for the relay port, limited to
   `RELAY_ALLOWED_CIDR`.
3. Registers the `tapo-nvr relay` scheduled task to start at boot as `SYSTEM`.
4. Starts the task and verifies that the port is listening.

The task runs `python -m tapo_nvr.relay`, so the interpreter must have the
package installed. If you installed into a virtual environment, set an absolute
`PYTHON_PATH` in `.env` first:

```dotenv
PYTHON_PATH=C:\path\to\tapo-nvr\.venv\Scripts\python.exe
```

```powershell
cd deploy\windows
.\install-relay.ps1
```

The script prints the interpreter it selected. Logs are written to
`%ProgramData%\tapo-nvr\relay.log` (rotated at 5 MB, three backups).

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

Logs are written to `%LOCALAPPDATA%\tapo-nvr\relay.log`. Run
`.\uninstall-relay.ps1` to remove the shortcut; without elevation it skips the
task and firewall cleanup and tells you so.

## Linux: systemd

Install the package into a virtual environment that the service user can read
(for example `/opt/tapo-nvr/venv`), then install the unit and its environment
file:

```bash
sudo mkdir -p /opt/tapo-nvr
sudo python3 -m venv /opt/tapo-nvr/venv
sudo /opt/tapo-nvr/venv/bin/pip install .

sudo install -D -m 0644 deploy/systemd/tapo-nvr-relay.service /etc/systemd/system/tapo-nvr-relay.service
sudo install -D -m 0644 deploy/systemd/relay.env.example /etc/tapo-nvr/relay.env
sudoedit /etc/tapo-nvr/relay.env
```

In `/etc/tapo-nvr/relay.env`, set at least:

```dotenv
CAMERA_HOST=192.168.1.50
PYTHON=/opt/tapo-nvr/venv/bin/python3
```

Then enable the unit:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tapo-nvr-relay
sudo journalctl -u tapo-nvr-relay -f
```

The unit runs as a `DynamicUser` with an empty capability set and a read-only
system, and it only needs to reach the camera and bind an unprivileged port.
Because `ProtectHome=yes` is set, keep the virtual environment and the package
outside `/home`. `RELAY_HOST=auto` resolves the Tailscale address at start;
restart the unit if the address changes.

To uninstall:

```bash
sudo systemctl disable --now tapo-nvr-relay
sudo rm /etc/systemd/system/tapo-nvr-relay.service /etc/tapo-nvr/relay.env
sudo systemctl daemon-reload
```

## Verify the relay

From the NVR host:

```bash
nc -vz <relay-tailscale-address> 8554
```

Or run `tapo-nvr inspect`, which performs this check and more.
