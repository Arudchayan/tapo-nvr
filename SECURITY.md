# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Select **Advisories** and click **Report a vulnerability**.
3. Include a description, reproduction steps, and the affected version
   (`tapo-nvr --version`).

You can expect an initial response within a few days. Please allow time for a
fix and release before public disclosure.

## Design notes

- **The relay is unauthenticated TCP.** It forwards bytes to the camera's RTSP
  port. Access control is delegated to Tailscale ACLs plus the
  `RELAY_ALLOWED_CIDR` allow list, which defaults to the Tailscale CGNAT range
  (`100.64.0.0/10`). Do not run the relay on a public interface.
- **Camera credentials** are stored in `.env` on the relay host (Git-ignored)
  and written to a mode `0600` environment file on the NVR host over SSH. They
  are never embedded in the Frigate YAML.
- **SSH host keys are verified** by default. `NVR_STRICT_HOST_KEY_CHECKING=false`
  disables verification and should only be used for initial setup or disposable
  hosts.
- **The Frigate UI port** is bound to the NVR host's Tailscale address and is
  not exposed publicly.

## Hardening recommendations

- Restrict the relay port to the NVR host with Tailscale ACLs. For example:

  ```json
  {
    "tagOwners": {
      "tag:relay": ["autogroup:admin"],
      "tag:nvr": ["autogroup:admin"]
    },
    "acls": [
      { "action": "accept", "src": ["tag:nvr"], "dst": ["tag:relay:8554"] }
    ]
  }
  ```

  This allows only the NVR host to reach the relay port, even if other devices
  are on the tailnet.
- Use SSH keys instead of passwords (`NVR_SSH_KEY`).
- Pin `FRIGATE_IMAGE` to a specific version and update deliberately.
- Keep `.env` readable only by your user (`chmod 600 .env` on POSIX).
- Rotate the camera account password if it has ever been committed or shared.
- The relay is IPv4-only and, on Windows, binds with `SO_EXCLUSIVEADDRUSE` so
  another local process cannot silently share the port.
