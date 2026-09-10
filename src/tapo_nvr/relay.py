"""Camera-only TCP relay bound to a private (Tailscale) address."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import logging
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import DEFAULT_ALLOWED_CIDR, ConfigError, Network, load_env_file, parse_networks

LOGGER = logging.getLogger("tapo_nvr.relay")
BUFFER_SIZE = 64 * 1024
RETRY_DELAY_SECONDS = 5
DEFAULT_MAX_CONNECTIONS = 32
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUPS = 3


@dataclass(frozen=True)
class RelayConfig:
    """Everything the relay needs to serve one camera."""

    bind: str
    listen_port: int
    target: str
    target_port: int
    allowed_networks: tuple[Network, ...] = field(
        default_factory=lambda: parse_networks([DEFAULT_ALLOWED_CIDR])
    )
    connect_timeout: float = 10.0
    max_connections: int = DEFAULT_MAX_CONNECTIONS


def tailscale_ipv4() -> str:
    """Return this host's Tailscale IPv4 address."""
    executable = shutil.which("tailscale")
    if executable is None:
        raise ConfigError(
            "The 'tailscale' executable was not found on PATH; set RELAY_HOST explicitly."
        )
    try:
        result = subprocess.run(
            [executable, "ip", "-4"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConfigError("'tailscale ip -4' did not respond within 10 seconds.") from exc
    for line in result.stdout.splitlines():
        address = line.strip()
        if address:
            return address
    raise ConfigError(
        "Could not determine this host's Tailscale IPv4 address; set RELAY_HOST explicitly."
    )


def resolve_relay_host(value: str) -> str:
    """Resolve ``auto`` to the local Tailscale IPv4 address."""
    value = (value or "").strip()
    if value and value.lower() != "auto":
        return value
    return tailscale_ipv4()


def is_allowed(address: str, networks: Sequence[Network]) -> bool:
    """Return whether ``address`` belongs to one of the allowed networks."""
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            address.split("%", 1)[0]
        )
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in network for network in networks)


def pump(source: socket.socket, destination: socket.socket) -> None:
    """Copy bytes from ``source`` to ``destination`` until EOF."""
    try:
        while True:
            data = source.recv(BUFFER_SIZE)
            if not data:
                return
            destination.sendall(data)
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            destination.shutdown(socket.SHUT_WR)


def handle_client(client: socket.socket, peer: str, config: RelayConfig) -> None:
    """Serve a single accepted connection."""
    if not is_allowed(peer, config.allowed_networks):
        LOGGER.warning("Rejected connection from %s", peer)
        client.close()
        return
    try:
        upstream = socket.create_connection(
            (config.target, config.target_port), timeout=config.connect_timeout
        )
    except OSError as exc:
        LOGGER.error("Could not reach %s:%s: %s", config.target, config.target_port, exc)
        client.close()
        return

    LOGGER.info("Relaying %s -> %s:%s", peer, config.target, config.target_port)
    client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    upstream.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # The connect timeout must not become a read timeout on the streaming socket.
    upstream.settimeout(None)
    with client, upstream:
        left = threading.Thread(target=pump, args=(client, upstream), daemon=True)
        right = threading.Thread(target=pump, args=(upstream, client), daemon=True)
        left.start()
        right.start()
        left.join()
        right.join()


class RelayServer:
    """A small accept loop that can be started and stopped in-process."""

    def __init__(self, config: RelayConfig) -> None:
        self._config = config
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._slots = threading.BoundedSemaphore(max(1, config.max_connections))

    @property
    def port(self) -> int:
        """The bound port, which is useful when ``listen_port`` is 0."""
        if self._listener is None:
            raise RuntimeError("The relay has not been started.")
        return int(self._listener.getsockname()[1])

    @property
    def alive(self) -> bool:
        """Whether the accept loop is still running."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Bind the listen socket and start accepting connections."""
        family = socket.AF_INET6 if ":" in self._config.bind else socket.AF_INET
        listener = socket.socket(family, socket.SOCK_STREAM)
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._config.bind, self._config.listen_port))
        listener.listen()
        listener.settimeout(0.5)
        self._listener = listener
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="relay-accept")
        self._thread.start()
        LOGGER.info("Relay listening on %s:%s", self._config.bind, self.port)

    def _handle_slot(self, client: socket.socket, peer: str) -> None:
        try:
            handle_client(client, peer, self._config)
        finally:
            self._slots.release()

    def _accept_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stopped.is_set():
            try:
                client, address = listener.accept()
            except TimeoutError:
                continue
            except OSError as exc:
                if self._stopped.is_set():
                    break
                LOGGER.warning("Accept failed (%s); continuing.", exc)
                time.sleep(0.1)
                continue
            if not self._slots.acquire(blocking=False):
                LOGGER.warning(
                    "Connection limit of %s reached; rejecting %s.",
                    self._config.max_connections,
                    address[0],
                )
                client.close()
                continue
            try:
                threading.Thread(
                    target=self._handle_slot,
                    args=(client, address[0]),
                    daemon=True,
                ).start()
            except RuntimeError:
                self._slots.release()
                client.close()
                LOGGER.error(
                    "Could not start a worker thread; closing connection from %s.",
                    address[0],
                )
                time.sleep(0.1)

    def stop(self) -> None:
        """Stop accepting connections and wait for the accept loop to end."""
        self._stopped.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


def _configure_logging(log_file: str | None, level: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=LOG_FILE_MAX_BYTES,
                backupCount=LOG_FILE_BACKUPS,
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a port number") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535, got {port}")
    return port


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the relay command."""
    parser = argparse.ArgumentParser(
        prog="tapo-nvr relay",
        description=(
            "Relay one RTSP camera over a private TCP port. Values not given on "
            "the command line are read from the environment file."
        ),
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=None,
        help="Environment file to read defaults from (default: ./.env when present).",
    )
    parser.add_argument(
        "--bind",
        default=None,
        help="Local address to listen on, or 'auto' for the Tailscale IPv4 address.",
    )
    parser.add_argument("--listen-port", type=_port, default=None)
    parser.add_argument("--target", default=None, help="Camera host name or IP address.")
    parser.add_argument("--target-port", type=_port, default=None)
    parser.add_argument(
        "--allowed-cidr",
        action="append",
        default=None,
        metavar="CIDR",
        help=(
            "Client ranges allowed to connect; repeat or comma-separate. "
            f"Defaults to {DEFAULT_ALLOWED_CIDR}."
        ),
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=DEFAULT_MAX_CONNECTIONS,
        metavar="N",
        help=f"Maximum simultaneous connections (default: {DEFAULT_MAX_CONNECTIONS}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument("--log-file", help="Also write rotating logs to this file.")
    return parser


def _pick(cli_value: object, env_values: dict[str, str], key: str, default: object) -> object:
    if cli_value is not None:
        return cli_value
    value = env_values.get(key)
    return value if value else default


def main(argv: Sequence[str] | None = None) -> int:
    """Run the relay until interrupted."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.log_file, args.log_level)

    env_values: dict[str, str] = {}
    default_env = Path(".env")
    try:
        if args.env is not None:
            env_values = load_env_file(args.env)
        elif default_env.is_file():
            env_values = load_env_file(default_env)
    except ConfigError as exc:
        LOGGER.error("%s", exc)
        return 2

    target = _pick(args.target, env_values, "CAMERA_HOST", "")
    if not target:
        parser.error("--target is required (or set CAMERA_HOST in the environment file).")

    allowed_values = args.allowed_cidr
    if allowed_values is None:
        env_allowed = env_values.get("RELAY_ALLOWED_CIDR", "")
        allowed_values = [env_allowed] if env_allowed else []
    try:
        networks = parse_networks(allowed_values)
    except ConfigError as exc:
        parser.error(str(exc))

    resolved_bind = str(_pick(args.bind, env_values, "RELAY_HOST", "auto"))
    listen_port = int(_pick(args.listen_port, env_values, "RELAY_PORT", 8554))
    target_port = int(_pick(args.target_port, env_values, "CAMERA_RTSP_PORT", 554))

    while True:
        try:
            config = RelayConfig(
                bind=resolve_relay_host(resolved_bind),
                listen_port=listen_port,
                target=str(target),
                target_port=target_port,
                allowed_networks=networks,
                max_connections=max(1, args.max_connections),
            )
            server = RelayServer(config)
            server.start()
            break
        except (OSError, ConfigError) as exc:
            LOGGER.warning(
                "Could not start the relay (%s); retrying in %ss.",
                exc,
                RETRY_DELAY_SECONDS,
            )
            time.sleep(RETRY_DELAY_SECONDS)

    stopped = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        LOGGER.info("Received signal %s; shutting down.", signum)
        stopped.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(OSError, ValueError):  # pragma: no cover - platform specific
            signal.signal(sig, _handle_signal)

    try:
        while not stopped.wait(1.0):
            if not server.alive:
                LOGGER.error("The accept loop stopped unexpectedly; exiting.")
                return 1
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
