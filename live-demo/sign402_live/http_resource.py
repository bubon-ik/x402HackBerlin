import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class X402ResourceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_probe_without_payment(self, target: str) -> dict[str, Any]:
        return self._get_probe(target)

    def get_probe_with_payment(self, target: str, payment_header: str) -> dict[str, Any]:
        return self._get_probe(target, payment_header)

    def _get_probe(self, target: str, payment_header: str | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode({"target": target})
        request = urllib.request.Request(f"{self.base_url}/probe?{query}")
        if payment_header:
            request.add_header("X-Payment", payment_header)

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            payload = json.loads(body)
            payload.setdefault("status", exc.code)
            return payload

