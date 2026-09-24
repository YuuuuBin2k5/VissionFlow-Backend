"""Forward a local TCP port through Tailscale's userspace SOCKS5 proxy."""

from __future__ import annotations

import logging
import os
import select
import socket
import socketserver
import struct


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("visionflow.tailscale_bridge")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("SOCKS5 proxy closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


_SOCKS5_STATUS = {
    0: "succeeded",
    1: "general SOCKS server failure",
    2: "connection not allowed by ruleset",
    3: "network unreachable",
    4: "host unreachable",
    5: "connection refused",
    6: "TTL expired",
    7: "command not supported",
    8: "address type not supported",
}


def _connect_socks5(proxy_host: str, proxy_port: int, target_host: str, target_port: int) -> socket.socket:
    logger.debug("SOCKS5: connecting to proxy %s:%s", proxy_host, proxy_port)
    try:
        upstream = socket.create_connection((proxy_host, proxy_port), timeout=15)
    except OSError as exc:
        raise ConnectionError(f"SOCKS5 proxy at {proxy_host}:{proxy_port} is unreachable: {exc}") from exc

    upstream.sendall(b"\x05\x01\x00")
    resp = _read_exact(upstream, 2)
    if resp != b"\x05\x00":
        upstream.close()
        raise ConnectionError(
            f"SOCKS5 proxy rejected unauthenticated negotiation (got {resp.hex()!r}, expected 0500)"
        )

    encoded_host = target_host.encode("idna")
    if len(encoded_host) > 255:
        upstream.close()
        raise ValueError("Database target hostname is too long")
    upstream.sendall(
        b"\x05\x01\x00\x03"
        + bytes([len(encoded_host)])
        + encoded_host
        + struct.pack("!H", target_port)
    )

    version, status, _reserved, address_type = _read_exact(upstream, 4)
    if version != 5 or status != 0:
        upstream.close()
        status_msg = _SOCKS5_STATUS.get(status, f"unknown status {status}")
        raise ConnectionError(
            f"SOCKS5 proxy could not reach {target_host}:{target_port} "
            f"(status={status}: {status_msg})"
        )
    if address_type == 1:
        _read_exact(upstream, 4)
    elif address_type == 3:
        _read_exact(upstream, _read_exact(upstream, 1)[0])
    elif address_type == 4:
        _read_exact(upstream, 16)
    else:
        upstream.close()
        raise ConnectionError(f"SOCKS5 proxy returned unknown address type {address_type}")
    _read_exact(upstream, 2)
    upstream.settimeout(None)
    logger.debug("SOCKS5: tunnel to %s:%s established", target_host, target_port)
    return upstream


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    while True:
        readable, _, exceptional = select.select(sockets, [], sockets, 60)
        if exceptional:
            return
        if not readable:
            continue
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            destination = right if source is left else left
            destination.sendall(data)


class BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        client_addr = self.client_address
        try:
            with _connect_socks5(
                server.proxy_host,
                server.proxy_port,
                server.target_host,
                server.target_port,
            ) as upstream:
                _relay(self.request, upstream)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.warning(
                "Database tunnel connection failed [client=%s:%s target=%s:%s]: %s",
                client_addr[0], client_addr[1],
                server.target_host, server.target_port,
                exc,
            )


class ThreadingBridge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, listen_address, handler, *, proxy_host, proxy_port, target_host, target_port):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.target_host = target_host
        self.target_port = target_port
        super().__init__(listen_address, handler)


def _wait_for_socks5_ready(host: str, port: int, timeout: int = 30) -> None:
    """Block until the SOCKS5 proxy at host:port accepts a connection."""
    import time
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            logger.info("SOCKS5 proxy at %s:%s is ready (attempt %s)", host, port, attempt)
            return
        except OSError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"SOCKS5 proxy at {host}:{port} did not become ready within {timeout}s"
                ) from exc
            logger.debug("SOCKS5 proxy not ready yet (attempt %s): %s", attempt, exc)
            time.sleep(min(1.0, remaining))


def main() -> None:
    listen_host = os.getenv("VISIONFLOW_DB_PROXY_LISTEN_HOST", "127.0.0.1")
    listen_port = int(os.getenv("VISIONFLOW_DB_PROXY_LISTEN_PORT", "15432"))
    proxy_host = os.getenv("VISIONFLOW_TAILSCALE_SOCKS_HOST", "127.0.0.1")
    proxy_port = int(os.getenv("VISIONFLOW_TAILSCALE_SOCKS_PORT", "1055"))
    target_host = _required("VISIONFLOW_TAILSCALE_DB_HOST")
    target_port = int(os.getenv("VISIONFLOW_TAILSCALE_DB_PORT", "5432"))

    logger.info(
        "Bridge config: listen=%s:%s socks5=%s:%s target=%s:%s",
        listen_host, listen_port, proxy_host, proxy_port, target_host, target_port,
    )

    # Wait for tailscaled's SOCKS5 server to be ready before accepting connections.
    _wait_for_socks5_ready(proxy_host, proxy_port, timeout=30)

    with ThreadingBridge(
        (listen_host, listen_port),
        BridgeHandler,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        target_host=target_host,
        target_port=target_port,
    ) as server:
        logger.info(
            "Database tunnel listening on %s:%s for target %s:%s",
            listen_host, listen_port, target_host, target_port,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
