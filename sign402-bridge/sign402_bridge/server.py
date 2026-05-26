import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .firefly import FireflyClient, find_firefly_port
from .policy import canonicalize_policy, hash_policy


class Sign402Handler(BaseHTTPRequestHandler):
    server_version = "Sign402Bridge/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"ok": True})
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/approve-policy":
            self._handle_approve_policy()
            return

        if self.path == "/approve-payment":
            self._handle_approve_payment()
            return

        self._send_json({"error": "not_found"}, status=404)

    def _handle_approve_policy(self) -> None:
        if not self._acquire_firefly():
            self._send_json(
                {
                    "approved": False,
                    "error": "firefly_busy",
                    "message": "Firefly is already handling another approval request.",
                },
                status=409,
            )
            return

        try:
            payload = self._read_json()
            policy = payload["policy"]
            if not isinstance(policy, dict):
                raise ValueError("policy must be an object")

            canonical = canonicalize_policy(policy)
            policy_hash = hash_policy(policy)
            approval = self.server.firefly.approve_policy_hash(policy_hash)

            if approval["approvedHash"] != policy_hash:
                raise ValueError("Firefly approved hash does not match policy hash.")

            self._send_json(
                {
                    "approved": True,
                    "policy": policy,
                    "canonicalPolicy": canonical,
                    "policyHash": policy_hash,
                    "firefly": approval,
                }
            )
        except Exception as exc:
            self._send_json({"approved": False, "error": str(exc)}, status=400)
        finally:
            self._release_firefly()

    def _handle_approve_payment(self) -> None:
        if not self._acquire_firefly():
            self._send_json(
                {
                    "approved": False,
                    "error": "firefly_busy",
                    "message": "Firefly is already handling another approval request.",
                },
                status=409,
            )
            return

        try:
            payload = self._read_json()
            payment_hash = str(payload["paymentHash"]).lower()
            approval = self.server.firefly.approve_payment_hash(payment_hash)

            if approval.get("approved") and approval["approvedHash"] != payment_hash:
                raise ValueError("Firefly approved hash does not match payment hash.")

            self._send_json(
                {
                    "approved": bool(approval.get("approved")),
                    "paymentHash": payment_hash,
                    "firefly": approval,
                },
                status=200 if approval.get("approved") else 400,
            )
        except Exception as exc:
            self._send_json({"approved": False, "error": str(exc)}, status=400)
        finally:
            self._release_firefly()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            raise ValueError("request body is empty")
        return json.loads(body.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _acquire_firefly(self) -> bool:
        lock = getattr(self.server, "firefly_lock", None)
        if lock is not None:
            return lock.acquire(blocking=False)

        if getattr(self.server, "firefly_busy", False):
            return False

        self.server.firefly_busy = True
        return True

    def _release_firefly(self) -> None:
        lock = getattr(self.server, "firefly_lock", None)
        if lock is not None:
            lock.release()
            return

        self.server.firefly_busy = False


class Sign402Server(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, firefly: FireflyClient):
        super().__init__(server_address, handler_class)
        self.firefly = firefly
        self.firefly_lock = threading.Lock()


def build_server(host: str, port: int, firefly_port: str) -> Sign402Server:
    firefly = FireflyClient(port=firefly_port)
    return Sign402Server((host, port), Sign402Handler, firefly)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Firefly bridge for Hermes Sign402.")
    parser.add_argument("--host", default=os.getenv("SIGN402_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SIGN402_PORT", "8088")))
    parser.add_argument("--firefly-port", default=os.getenv("FIREFLY_PORT"))
    args = parser.parse_args()

    firefly_port = args.firefly_port or find_firefly_port()
    server = build_server(args.host, args.port, firefly_port)

    print(f"Sign402 bridge listening on http://{args.host}:{args.port}")
    print(f"Firefly port: {firefly_port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
