import io
import json
import unittest
from unittest.mock import Mock, patch

from sign402_bridge.server import Sign402Handler


class DummyServer:
    firefly = Mock()
    firefly_busy = False


class FakeSocket:
    def __init__(self, request):
        self.rfile = io.BytesIO(request)
        self.wfile = io.BytesIO()

    def makefile(self, mode, buffering=None):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, data):
        self.wfile.write(data)


class ServerTests(unittest.TestCase):
    def make_handler(self, body, path="/approve-policy"):
        request = (
            f"POST {path} HTTP/1.1\r\n".encode()
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Content-Type: application/json\r\n"
            + b"\r\n"
            + body
        )
        socket = FakeSocket(request)
        handler = Sign402Handler(socket, ("127.0.0.1", 12345), DummyServer())
        handler.response = socket.wfile
        return handler

    def test_approve_policy_endpoint_returns_firefly_approval(self):
        policy_hash = "a" * 64
        DummyServer.firefly.reset_mock()
        DummyServer.firefly_busy = False
        DummyServer.firefly.approve_policy_hash.return_value = {
            "approved": True,
            "approvedHash": policy_hash,
            "deviceModel": 262,
            "deviceSerial": 1056,
            "raw": "<OK",
        }

        with patch("sign402_bridge.server.hash_policy", return_value=policy_hash), patch(
            "sys.stderr", io.StringIO()
        ):
            handler = self.make_handler(
                json.dumps({"policy": {"agentId": "hermes-demo"}}).encode()
            )

        response = handler.response.getvalue().decode("utf-8", "replace")

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"approved": true', response)
        self.assertIn(f'"policyHash": "{policy_hash}"', response)
        DummyServer.firefly.approve_policy_hash.assert_called_once_with(policy_hash)

    def test_approve_policy_endpoint_rejects_when_firefly_is_busy(self):
        DummyServer.firefly.reset_mock()
        DummyServer.firefly_busy = True

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                json.dumps({"policy": {"agentId": "hermes-demo"}}).encode()
            )

        response = handler.response.getvalue().decode("utf-8", "replace")

        self.assertIn("HTTP/1.0 409 Conflict", response)
        self.assertIn('"error": "firefly_busy"', response)
        DummyServer.firefly.approve_policy_hash.assert_not_called()

    def test_approve_payment_endpoint_returns_firefly_approval(self):
        payment_hash = "b" * 64
        DummyServer.firefly.reset_mock()
        DummyServer.firefly_busy = False
        DummyServer.firefly.approve_payment_hash.return_value = {
            "approved": True,
            "approvedHash": payment_hash,
            "deviceModel": 262,
            "deviceSerial": 1056,
            "raw": "<OK",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                json.dumps({"paymentHash": payment_hash}).encode(),
                path="/approve-payment",
            )

        response = handler.response.getvalue().decode("utf-8", "replace")

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"approved": true', response)
        self.assertIn(f'"paymentHash": "{payment_hash}"', response)
        DummyServer.firefly.approve_payment_hash.assert_called_once_with(payment_hash)

    def test_approve_payment_endpoint_rejects_hash_mismatch(self):
        payment_hash = "b" * 64
        DummyServer.firefly.reset_mock()
        DummyServer.firefly_busy = False
        DummyServer.firefly.approve_payment_hash.return_value = {
            "approved": True,
            "approvedHash": "c" * 64,
            "deviceModel": 262,
            "deviceSerial": 1056,
            "raw": "<OK",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                json.dumps({"paymentHash": payment_hash}).encode(),
                path="/approve-payment",
            )

        response = handler.response.getvalue().decode("utf-8", "replace")

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        self.assertIn("approved hash does not match", response)


if __name__ == "__main__":
    unittest.main()
