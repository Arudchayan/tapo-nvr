# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-10

First open-source release.

### Added

- `tapo-nvr` command-line tool with `deploy`, `inspect`, `fetch-clip`, and
  `relay` subcommands.
- Camera-only TCP relay bound to the Tailscale address with a CIDR allow list
  and per-connection logging.
- Frigate configuration rendering with `{FRIGATE_*}` placeholder credentials,
  configurable retention, detection streams, and optional VAAPI acceleration.
- SSH management helpers with key or password authentication, strict host key
  checking by default, and deadlock-free command output handling.
- Windows boot-time scheduled task installer, non-admin Startup shortcut
  installer, and uninstaller.
- systemd unit with hardening for Linux relay hosts.
- Health checks and JSON inspection output with credential redaction.
- MIT license, contribution guide, code of conduct, security policy, issue and
  pull request templates, and CI (Ubuntu and Windows, Python 3.10-3.13).
- Wheel build and clean-install smoke test in CI.

### Fixed

- `python -m tapo_nvr.relay` now starts the relay; the missing entry-point
  guard previously made the module exit silently.
- `tapo-nvr inspect` now fails for a closed relay port, a stopped or missing
  container, and a missing image, and treats the GPU device as informational
  when acceleration is disabled.
- The relay survives transient `accept()` errors, guards against worker-thread
  exhaustion, caps concurrent connections, clears the connect timeout before
  streaming, and rotates its log file.
- `.env` files with a UTF-8 byte-order mark are accepted; UTF-16 files produce
  a clear error. Unknown keys are reported, `export` prefixes are supported,
  and quoted passwords keep leading/trailing spaces.
- Credential redaction handles passwords containing `@` or `/`.
- The recordings layout is consistently `{NVR_BASE_PATH}/frigate/storage` in
  code, docs, and defaults.
- The Windows installer runs from an admin-only working directory, validates
  host values and the interpreter path, resolves `auto` at runtime, and warns
  about duplicate Startup shortcuts. The uninstaller works without elevation
  for user-scope installs.
- The systemd unit takes its interpreter from `PYTHON`, supports virtual
  environments outside `/home`, and limits restart loops.
