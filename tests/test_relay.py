"""Tests for the camera-only TCP relay."""

from __future__ import annotations

import socket
import threading

from tapo_nvr.config import parse_networks
from tapo_nvr.relay import RelayConfig, RelayServer, is_allowed


def _start_echo_server() -> tuple[int, threading.Thread]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            while True:
                data = connection.recv(4096)
                if not data:
                    break
                connection.sendall(data)
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, thread


def _start_relay(target_port: int, allowed: list[str]) -> RelayServer:
    server = RelayServer(
        RelayConfig(
            bind="127.0.0.1",
            listen_port=0,
            target="127.0.0.1",
            target_port=target_port,
            allowed_networks=parse_networks(allowed),
        )
    )
    server.start()
    return server


def test_relay_forwards_traffic_between_both_sides() -> None:
    echo_port, echo_thread = _start_echo_server()
    server = _start_relay(echo_port, ["127.0.0.1/32"])
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as client:
            client.sendall(b"ping")
            assert client.recv(4) == b"ping"
    finally:
        server.stop()
    echo_thread.join(timeout=5)


def test_relay_rejects_clients_outside_the_allow_list() -> None:
    echo_port, _ = _start_echo_server()
    server = _start_relay(echo_port, ["10.0.0.0/8"])
    try:
        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as client:
            client.settimeout(5)
            assert client.recv(1) == b""
    finally:
        server.stop()


def test_is_allowed_handles_ipv4_mapped_ipv6() -> None:
    networks = parse_networks(["100.64.0.0/10"])

    assert is_allowed("100.64.1.2", networks)
    assert not is_allowed("192.168.1.2", networks)
    assert is_allowed("::ffff:100.64.1.2", networks)
    assert not is_allowed("not-an-ip", networks)
