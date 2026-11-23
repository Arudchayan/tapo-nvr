# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-23

### Added

- `tapo-nvr sync` copies new recordings from the camera's microSD card to a
  local folder, such as a Google Drive folder, for installations without an
  always-on NVR host. It supports date ranges, dry runs, overwrite, and
  skip-existing behavior, and leaves clips that are still recording for the next
  run. Requires the optional `pytapo` dependency and FFmpeg.
- `tapo-nvr record` records the camera's RTSP stream on the laptop in
  clock-aligned segments, publishes finished segments to a folder (for example
  a Google Drive mount), and cleans up local copies after a grace period. It
  includes a preflight check, automatic ffmpeg restarts, ffmpeg segment-list
  close detection, process-tree shutdown, a stall watchdog, a single-instance
  lock, a rotating log, a JSON status heartbeat, a staging free-space guard, and
  optional `RECORD_OUTPUT_KEEP_DAYS` retention for the published files.
- `deploy/windows/start-record.ps1`, a small logon supervisor that restarts the
  recorder after a failure.
- Both deployment shapes are documented side by side: the original relay +
  Frigate NVR and the no-always-on-host laptop/Drive modes.

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
