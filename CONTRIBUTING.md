# Contributing to tapo-nvr

Thanks for taking the time to contribute. This document covers the development
setup, expectations, and pull request process.

## Reporting bugs and requesting features

- Search existing issues first.
- Use the issue templates.
- **Redact secrets.** Never paste camera passwords, `.env` contents, Tailscale
  addresses, or unredacted `rtsp://user:password@host` URLs.

## Development setup

```bash
git clone https://github.com/Arudchayan/tapo-nvr.git
cd tapo-nvr
python -m venv .venv

# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest
```

Use `ruff format .` to apply formatting automatically. CI runs lint on Linux
and the test matrix on Linux and Windows, for Python 3.10 through 3.13.

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat: add multi-camera support`
- `fix: retry relay bind when Tailscale starts late`
- `docs: document SSH key setup`
- `test: cover CIDR parsing`
- `chore: bump GitHub Actions`

## Pull requests

- Keep changes focused; one logical change per pull request.
- Add or update tests for behavior changes.
- Update `README.md`, `docs/`, and `CHANGELOG.md` when user-facing behavior
  changes.
- Describe how you tested the change (OS, Python version, camera model if
  relevant).

## Security

Do not report vulnerabilities through public issues. Follow
[SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
