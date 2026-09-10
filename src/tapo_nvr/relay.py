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
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .config import DEFAULT_ALLOWED_CIDR, ConfigError, Network, parse_networks

LOGGER = logging.getLogger("tapo_nvr.relay")
BUFFER_SIZE = 64 * 1024
RETRY_DELAY_SECONDS = 5


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


def tailscale_ipv4() -> str:
    """Return this host's Tailscale IPv4 address."""
    executable = shutil.which("tailscale")
    if executable is None:
        raise ConfigError(
            "The 'tailscale' executable was not found on PATH; set RELAY_HOST explicitly."
        )
    result = subprocess.run([executable, "ip", "-4"], capture_output=True, text=True, check=False)
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

    @property
    def port(self) -> int:
        """The bound port, which is useful when ``listen_port`` is 0."""
        if self._listener is None:
            raise RuntimeError("The relay has not been started.")
        return int(self._listener.getsockname()[1])

    def start(self) -> None:
        """Bind the listen socket and start accepting connections."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._config.bind, self._config.listen_port))
        listener.listen()
        listener.settimeout(0.5)
        self._listener = listener
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="relay-accept")
        self._thread.start()
        LOGGER.info("Relay listening on %s:%s", self._config.bind, self.port)

    def _accept_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stopped.is_set():
            try:
                client, address = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(
                target=handle_client,
                args=(client, address[0], self._config),
                daemon=True,
            ).start()

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
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the relay command."""
    parser = argparse.ArgumentParser(
        prog="tapo-nvr relay",
        description="Relay one RTSP camera over a private TCP port.",
    )
    parser.add_argument(
        "--bind",
        default="auto",
        help="Local address to listen on, or 'auto' for the Tailscale IPv4 address.",
    )
    parser.add_argument("--listen-port", type=int, default=8554)
    parser.add_argument("--target", required=True, help="Camera host name or IP address.")
    parser.add_argument("--target-port", type=int, default=554)
    parser.add_argument(
        "--allowed-cidr",
        action="append",
        default=[],
        metavar="CIDR",
        help=(
            "Client ranges allowed to connect; repeat or comma-separate. "
            f"Defaults to {DEFAULT_ALLOWED_CIDR}."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument("--log-file", help="Also write logs to this file.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the relay until interrupted."""
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_file, args.log_level)
    networks = parse_networks(args.allowed_cidr)

    while True:
        try:
            config = RelayConfig(
                bind=resolve_relay_host(args.bind),
                listen_port=args.listen_port,
                target=args.target,
                target_port=args.target_port,
                allowed_networks=networks,
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
            pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
