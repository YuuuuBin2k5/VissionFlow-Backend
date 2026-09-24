import socket
import sys
import threading
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT / "scripts"))

from tailscale_tcp_bridge import BridgeHandler, ThreadingBridge  # noqa: E402


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("unexpected EOF")
        data += chunk
    return data


class FakeSocksProxy:
    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.requested_host = None
        self.requested_port = None
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _serve(self) -> None:
        with self.listener:
            connection, _ = self.listener.accept()
            with connection:
                self.assert_bytes(_read_exact(connection, 3), b"\x05\x01\x00")
                connection.sendall(b"\x05\x00")
                header = _read_exact(connection, 5)
                self.assert_bytes(header[:4], b"\x05\x01\x00\x03")
                hostname = _read_exact(connection, header[4])
                self.requested_host = hostname.decode("idna")
                self.requested_port = int.from_bytes(_read_exact(connection, 2), "big")
                connection.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                payload = connection.recv(1024)
                connection.sendall(payload)

    @staticmethod
    def assert_bytes(actual: bytes, expected: bytes) -> None:
        if actual != expected:
            raise AssertionError(f"expected {expected!r}, got {actual!r}")


class TailscaleTcpBridgeTests(unittest.TestCase):
    def test_forwards_tcp_through_socks5_domain_target(self) -> None:
        proxy = FakeSocksProxy()
        proxy.start()
        bridge = ThreadingBridge(
            ("127.0.0.1", 0),
            BridgeHandler,
            proxy_host="127.0.0.1",
            proxy_port=proxy.port,
            target_host="visionflow-db",
            target_port=5432,
        )
        bridge_thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        bridge_thread.start()
        try:
            with socket.create_connection(bridge.server_address, timeout=3) as client:
                client.sendall(b"postgres-probe")
                self.assertEqual(client.recv(1024), b"postgres-probe")
            proxy.thread.join(timeout=3)
            self.assertEqual(proxy.requested_host, "visionflow-db")
            self.assertEqual(proxy.requested_port, 5432)
        finally:
            bridge.shutdown()
            bridge.server_close()


if __name__ == "__main__":
    unittest.main()
