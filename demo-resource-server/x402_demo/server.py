import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .core import (
    build_payment_required,
    build_probe_result,
    parse_payment_proof,
    verify_payment_proof,
)


USED_PAYMENT_INTENTS: set[str] = set()
PENDING_REQUIREMENTS: dict[str, dict] = {}


class X402DemoHandler(BaseHTTPRequestHandler):
    server_version = "HermesX402Demo/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"ok": True})
            return
        if parsed.path != "/probe":
            self._send_json({"error": "not_found"}, status=404)
            return

        query = parse_qs(parsed.query)
        target = query.get("target", [""])[0]
        if not target:
            self._send_json({"error": "target query parameter is required"}, status=400)
            return

        payment_header = self.headers.get("X-Payment")

        if not payment_header:
            requirement_payload = build_payment_required(target)
            requirement = requirement_payload["paymentRequirements"]
            PENDING_REQUIREMENTS[requirement["paymentIntent"]] = requirement
            self._send_json(requirement_payload, status=402)
            return

        try:
            payment_proof = parse_payment_proof(payment_header)
            payment_intent = str(payment_proof.get("paymentIntent", ""))
            requirement = PENDING_REQUIREMENTS.get(payment_intent)
            if requirement is None:
                self._send_json(
                    {
                        "error": "payment_verification_failed",
                        "reason": "unknown or expired paymentIntent",
                    },
                    status=402,
                )
                return

            verification = verify_payment_proof(
                payment_proof,
                requirement,
                USED_PAYMENT_INTENTS,
            )
            if not verification["ok"]:
                self._send_json(
                    {
                        "error": "payment_verification_failed",
                        "reason": verification["reason"],
                        "paymentRequirements": requirement,
                    },
                    status=402,
                )
                return

            USED_PAYMENT_INTENTS.add(requirement["paymentIntent"])
            PENDING_REQUIREMENTS.pop(requirement["paymentIntent"], None)
            self._send_json(build_probe_result(target, payment_proof))
        except Exception as exc:
            self._send_json({"error": "invalid_payment", "reason": str(exc)}, status=400)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo x402 protected resource server.")
    parser.add_argument("--host", default=os.getenv("X402_DEMO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("X402_DEMO_PORT", "8090")))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), X402DemoHandler)
    print(f"x402 demo resource server listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
