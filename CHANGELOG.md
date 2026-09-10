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
