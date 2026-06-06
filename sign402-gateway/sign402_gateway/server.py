import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[2]
SIGN402_BRIDGE_DIR = ROOT_DIR / "sign402-bridge"
PAYMENT_EXECUTOR_DIR = ROOT_DIR / "payment-executor"
LIVE_DEMO_DIR = ROOT_DIR / "live-demo"
DEMO_RESOURCE_SERVER_DIR = ROOT_DIR / "demo-resource-server"
DEFAULT_EVENT_STORE_PATH = ROOT_DIR / "demo-dashboard" / "latest-run.json"
DEFAULT_AGENT_STATE_PATH = ROOT_DIR / "demo-dashboard" / "agent-state.json"

for package_dir in (SIGN402_BRIDGE_DIR, PAYMENT_EXECUTOR_DIR, LIVE_DEMO_DIR, DEMO_RESOURCE_SERVER_DIR):
    package_path = str(package_dir)
    if package_path not in sys.path:
        sys.path.insert(0, package_path)

from sign402_live.flow import build_payment_commitment
from sign402_live.http_resource import X402ResourceClient
from sign402_bridge.firefly import FireflyClient, find_firefly_port
from sign402_bridge.policy import canonicalize_policy, hash_policy
from sign402_executor.executor import build_x402_avm_payment_signature_header, execute_payment
from x402_demo.core import encode_payment_proof

from .goplausible import fetch_x402_paid_resource, fetch_x402_payment_required, normalize_x402_payment_required

HEX_32_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_QR_DATA_CHARS = 2048
REJECTED_TOOL_RETRY_SUPPRESSION_SECONDS = 120.0
DEFAULT_TESTNET_ALGOD_URLS = [
    "https://testnet-api.algonode.cloud",
    "https://testnet-api.4160.nodely.dev",
    "https://testnet-api.algonode.network",
    "https://algorand-testnet-algod.gateway.tatum.io",
]
EURD_ASA_ID = 1221682136
EURD_ASSET_DECIMALS = 2
EURD_NETWORK = "algorand-mainnet"
EURD_MAX_AMOUNT_ATOMIC = 100
DEFAULT_QUANTOZ_WALLET_ENV_PATH = ROOT_DIR.parent / "quantoz-mainnet-wallet.env"
DEFAULT_MAINNET_ALGOD_URLS = [
    "https://mainnet-api.4160.nodely.dev",
    "https://mainnet-api.algonode.network",
    "https://mainnet-api.algonode.cloud",
    "https://algorand-mainnet-algod.gateway.tatum.io",
]


PAYMENT_RAILS: dict[str, dict[str, Any]] = {
    "algorand-testnet-usdc": {
        "id": "algorand-testnet-usdc",
        "name": "Algorand TestNet USDC",
        "status": "live_demo_default",
        "network": "algorand-testnet",
        "scheme": "x402-avm",
        "asset": "USDC",
        "assetId": "10458941",
        "assetDecimals": 6,
        "facilitator": "https://x402.goplausible.xyz",
        "requiresKyc": False,
        "requiresMainnetFunds": False,
        "description": "Current hackathon demo rail for safe TestNet x402 payments.",
    },
    "quantoz-eurd-mainnet": {
        "id": "quantoz-eurd-mainnet",
        "name": "Quantoz EURD MainNet",
        "status": "live_optional",
        "network": EURD_NETWORK,
        "scheme": "exact-asa-transfer",
        "asset": "EURD",
        "assetId": str(EURD_ASA_ID),
        "assetDecimals": EURD_ASSET_DECIMALS,
        "facilitator": "https://x402algo.ai.quantozpay.com",
        "sdk": "@ever_amsterdam/x402-euro-eurd",
        "requiredEnv": ["QUANTOZ_WALLET_ENV"],
        "requiresKyc": True,
        "requiresMainnetFunds": True,
        "description": "Optional live EURD mainnet transfer rail for MiCA-aligned euro agent payments.",
    },
}


PAID_TOOLS: dict[str, dict[str, Any]] = {
    "goplausible.weather": {
        "id": "goplausible.weather",
        "name": "GoPlausible Weather",
        "kind": "external_x402_resource",
        "source": "goplausible-x402",
        "description": "Paid weather forecast API exposed through official x402 on Algorand.",
        "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
        "command": "buy goplausible weather",
        "mcpStyleName": "get_weather",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Optional city to display in the weather receipt, e.g. Tokyo.",
                }
            },
            "required": [],
        },
    },
    "sign402.qr": {
        "id": "sign402.qr",
        "name": "Sign402 QR Code",
        "kind": "local_artifact_after_x402_payment",
        "source": "sign402-gateway",
        "description": "Paid QR code generation for links, text, or agent artifacts.",
        "resourceUrl": "sign402://tools/qr",
        "paymentResourceUrl": "https://x402.goplausible.xyz/examples/weather",
        "fireflyContext": {
            "title": "x402 QR CODE",
            "service": "Sign402 Generator",
        },
        "command": "buy qr code",
        "mcpStyleName": "create_qr_code",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to encode as a QR code.",
                },
                "text": {
                    "type": "string",
                    "description": "Plain text to encode as a QR code.",
                },
                "data": {
                    "type": "string",
                    "description": "Generic QR payload.",
                },
                "target": {
                    "type": "string",
                    "description": "Alias for url/text/data used by agents.",
                },
            },
            "required": [],
        },
    },
    "quantoz.eurd.transfer": {
        "id": "quantoz.eurd.transfer",
        "name": "Quantoz EURD Transfer",
        "kind": "local_mainnet_eurd_transfer",
        "source": "sign402-gateway",
        "description": "Firefly-approved EURD ASA transfer on Algorand MainNet.",
        "resourceUrl": "sign402://payments/eurd-transfer",
        "paymentResourceUrl": "sign402://payments/eurd-transfer",
        "paymentStandard": "sign402-direct-transfer",
        "network": EURD_NETWORK,
        "asset": str(EURD_ASA_ID),
        "assetName": "EURD",
        "price": "variable EURD",
        "priceAtomic": "variable",
        "inspectEndpoint": "/agent/tools",
        "buyEndpoint": "/agent/pay-eurd",
        "command": "pay eurd",
        "mcpStyleName": "pay_eurd",
        "inputSchema": {
            "type": "object",
            "properties": {
                "receiver": {
                    "type": "string",
                    "description": "Whitelisted Algorand MainNet receiver address.",
                },
                "amount": {
                    "type": "string",
                    "description": "EURD amount with up to 2 decimals, e.g. 0.01.",
                },
                "amountAtomic": {
                    "type": "string",
                    "description": "Atomic EURD amount; 1 equals 0.01 EURD.",
                },
                "memo": {
                    "type": "string",
                    "description": "Optional note for the payment approval commitment.",
                },
            },
            "required": ["receiver"],
        },
    },
}

PAID_TOOL_ALIASES = {
    "weather": "goplausible.weather",
    "goplausible-weather": "goplausible.weather",
    "goplausible_weather": "goplausible.weather",
    "get_weather": "goplausible.weather",
    "qr": "sign402.qr",
    "qrcode": "sign402.qr",
    "qr-code": "sign402.qr",
    "qr_code": "sign402.qr",
    "create_qr_code": "sign402.qr",
    "eurd": "quantoz.eurd.transfer",
    "pay_eurd": "quantoz.eurd.transfer",
    "quantoz-eurd": "quantoz.eurd.transfer",
    "quantoz_eurd": "quantoz.eurd.transfer",
}


class Sign402GatewayHandler(BaseHTTPRequestHandler):
    server_version = "Sign402Gateway/0.1"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "sign402-gateway",
                    "endpoints": [
                        "/approve-policy",
                        "/approve-payment",
                        "/execute-payment",
                        "/events/latest",
                        "/agent/buy-probe",
                        "/agent/tools",
                        "/agent/rails",
                        "/agent/manifest",
                        "/agent/inspect-tool",
                        "/agent/buy-tool",
                        "/agent/pay-eurd",
                        "/agent/inspect-x402",
                        "/agent/buy-x402",
                        "/.well-known/x402.json",
                    ],
                }
            )
            return
        if path in ("/agent/manifest", "/.well-known/x402.json"):
            self._handle_agent_manifest()
            return
        if path == "/agent/tools":
            self._handle_agent_tools()
            return
        if path == "/agent/rails":
            self._handle_agent_rails()
            return
        if path == "/events/latest":
            self._handle_get_latest_event()
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/approve-policy":
            self._handle_approve_policy()
            return
        if path == "/approve-payment":
            self._handle_approve_payment()
            return
        if path == "/execute-payment":
            self._handle_execute_payment()
            return
        if path == "/agent/buy-probe":
            self._handle_agent_buy_probe()
            return
        if path == "/agent/inspect-tool":
            self._handle_agent_inspect_tool()
            return
        if path == "/agent/buy-tool":
            self._handle_agent_buy_tool()
            return
        if path == "/agent/pay-eurd":
            self._handle_agent_pay_eurd()
            return
        if path == "/agent/inspect-x402":
            self._handle_agent_inspect_x402()
            return
        if path == "/agent/buy-x402":
            self._handle_agent_buy_x402()
            return
        self._send_json({"error": "not_found"}, status=404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_approve_policy(self) -> None:
        if not self._acquire_firefly():
            self._send_json(_busy_payload(), status=409)
            return

        try:
            payload = self._read_json()
            policy = payload["policy"]
            if not isinstance(policy, dict):
                raise ValueError("policy must be an object")

            canonical = canonicalize_policy(policy)
            policy_hash = hash_policy(policy)
            approval = self.server.firefly.approve_payment_hash(policy_hash)

            if approval["approvedHash"] != policy_hash:
                raise ValueError("Firefly approved hash does not match policy hash.")

            response = {
                "approved": True,
                "policy": policy,
                "canonicalPolicy": canonical,
                "policyHash": policy_hash,
                "firefly": approval,
            }
            self.server.agent_state_store.write_policy(response)
            self._send_json(response)
        except TimeoutError:
            self._send_json(_firefly_timeout_payload(approved=False), status=504)
        except Exception as exc:
            self._send_json({"approved": False, "error": str(exc)}, status=400)
        finally:
            self._release_firefly()

    def _handle_approve_payment(self) -> None:
        if not self._acquire_firefly():
            self._send_json(_busy_payload(), status=409)
            return

        try:
            payload = self._read_json()
            payment_hash = _read_hash(payload, "paymentHash")
            payment_commitment = payload.get("paymentCommitment")
            context_lines = _payment_context_lines(
                payment_commitment if isinstance(payment_commitment, dict) else None
            )
            approval = self.server.firefly.approve_payment_hash(
                payment_hash,
                context_lines=context_lines,
            )

            if approval.get("approved") and approval["approvedHash"] != payment_hash:
                raise ValueError("Firefly approved hash does not match payment hash.")

            if approval.get("approved"):
                self.server.agent_state_store.record_payment_approval(payment_hash, approval)

            self._send_json(
                {
                    "approved": bool(approval.get("approved")),
                    "paymentHash": payment_hash,
                    "firefly": approval,
                },
                status=200 if approval.get("approved") else 400,
            )
        except TimeoutError:
            self._send_json(_firefly_timeout_payload(approved=False), status=504)
        except Exception as exc:
            self._send_json({"approved": False, "error": str(exc)}, status=400)
        finally:
            self._release_firefly()

    def _handle_execute_payment(self) -> None:
        try:
            payload = self._read_json()
            policy_hash = _read_hash(payload, "policyHash")
            payment_approval_hash = _read_hash(payload, "paymentApprovalHash")
            requirement = payload["paymentRequirements"]
            _validate_payment_requirements(requirement)

            expected_approval_hash = build_payment_commitment(
                requirement,
                policy_hash,
            )["paymentHash"]
            if payment_approval_hash != expected_approval_hash:
                raise ValueError(
                    "paymentApprovalHash does not match payment commitment"
                )

            policy_state = self.server.agent_state_store.read_policy()
            if policy_state is None:
                raise ValueError("No Firefly-approved policy stored. Call /approve-policy first.")
            policy = policy_state["policy"]
            approved_policy_hash = str(policy_state["firefly"]["approvedHash"]).lower()
            if approved_policy_hash != policy_hash:
                raise ValueError("Stored policy hash does not match Firefly approval.")

            self.server.agent_state_store.validate_policy_allows(
                policy,
                policy_hash,
                requirement,
            )
            if not self.server.agent_state_store.consume_payment_approval(
                payment_approval_hash
            ):
                raise ValueError(
                    "No unused Firefly approval for paymentApprovalHash"
                )

            payment = self.server.payment_executor(requirement, policy_hash)
            self.server.agent_state_store.record_payment(
                policy_hash,
                str(requirement["paymentIntent"]),
                int(str(requirement["amountAtomic"])),
            )
            self._send_json(
                {
                    "ok": True,
                    "policyHash": policy_hash,
                    "paymentApprovalHash": payment_approval_hash,
                    "payment": payment,
                }
            )
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)

    def _handle_get_latest_event(self) -> None:
        event = self.server.event_store.read()
        self._send_json({"ok": event is not None, "event": event})

    def _handle_agent_buy_probe(self) -> None:
        if not self._acquire_firefly():
            self._send_json(_busy_payload(), status=409)
            return

        try:
            payload = self._read_json()
            target = str(payload.get("target", "")).strip()
            if not target:
                raise ValueError("target is required")

            result = self.server.agent_buy_probe(target)
            self._send_json(result)
        except TimeoutError:
            self._send_json(_firefly_timeout_payload(decision=True), status=504)
        except Exception as exc:
            self._send_json(_exception_payload(exc), status=400)
        finally:
            self._release_firefly()

    def _handle_agent_tools(self) -> None:
        self._send_json(
            {
                "ok": True,
                "mode": "paid_tool_catalog",
                "tools": list(PAID_TOOLS.values()),
                "nextStep": "POST /agent/inspect-tool with {\"tool\":\"goplausible.weather\"}, then POST /agent/buy-tool.",
            }
        )

    def _handle_agent_rails(self) -> None:
        self._send_json(_agent_rails())

    def _handle_agent_manifest(self) -> None:
        self._send_json(_agent_manifest())

    def _handle_agent_inspect_tool(self) -> None:
        try:
            payload = self._read_json()
            tool = _resolve_paid_tool(payload)
            policy_hash = self._policy_hash_from_payload_or_state(payload)
            inspection = self.server.x402_inspector(_tool_payment_resource_url(tool), policy_hash)
            result = _tool_result(tool, inspection, _tool_request_context(payload))
            result["nextStep"] = "If acceptable, POST /agent/buy-tool with the same tool id. Firefly approval is required before payment."
            self._send_json(result)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)

    def _handle_agent_buy_tool(self) -> None:
        try:
            payload = self._read_json()
            tool = _resolve_paid_tool(payload)
            request_context = _tool_request_context(payload)
            _validate_tool_request(tool, request_context)
            if tool.get("id") != "quantoz.eurd.transfer":
                rejected_retry = self._read_rejected_tool_retry(tool, request_context)
                if rejected_retry is not None:
                    self._send_json(rejected_retry)
                    return
        except Exception as exc:
            self._send_json({"decision": "rejected", "ok": False, "error": str(exc)}, status=400)
            return

        if not self._acquire_firefly():
            self._send_json(_busy_payload(), status=409)
            return

        try:
            if tool.get("id") == "quantoz.eurd.transfer":
                event, status = self._execute_agent_pay_eurd(payload)
                enriched = _tool_result(tool, event, request_context)
                if enriched.get("ok"):
                    self.server.event_store.write(enriched)
                self._send_json(enriched, status=status)
                return

            firefly_context = tool.get("fireflyContext")
            if isinstance(firefly_context, dict):
                result = self.server.x402_buyer(
                    _tool_payment_resource_url(tool),
                    firefly_context=firefly_context,
                )
            else:
                result = self.server.x402_buyer(_tool_payment_resource_url(tool))
            enriched = _tool_result(tool, result, request_context)
            enriched["decision"] = result.get("decision", "approved_and_executed")
            enriched["ok"] = bool(result.get("ok", False))
            if enriched.get("ok"):
                self.server.event_store.write(enriched)
            elif enriched.get("decision") == "rejected_by_firefly":
                self._store_rejected_tool_retry(tool, request_context, enriched)
            self._send_json(enriched)
        except TimeoutError:
            self._send_json(_firefly_timeout_payload(decision=True), status=504)
        except Exception as exc:
            self._send_json(_exception_payload(exc), status=400)
        finally:
            self._release_firefly()

    def _handle_agent_pay_eurd(self) -> None:
        if not self._acquire_firefly():
            self._send_json(_busy_payload(), status=409)
            return

        try:
            payload = self._read_json()
            event, status = self._execute_agent_pay_eurd(payload)
            self.server.event_store.write(event)
            self._send_json(event, status=status)
        except TimeoutError:
            self._send_json(_firefly_timeout_payload(decision=True), status=504)
        except Exception as exc:
            self._send_json(_exception_payload(exc), status=400)
        finally:
            self._release_firefly()

    def _execute_agent_pay_eurd(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        request = _eurd_payment_request(payload)
        payment_hash = _hash_json(request["paymentCommitment"])
        approval = self.server.firefly.approve_payment_hash(
            payment_hash,
            context_lines=[
                "EURD PAYMENT",
                _format_eurd_amount(request["amountAtomic"]),
                _short_address(request["receiver"]),
            ],
        )
        if not approval.get("approved"):
            return (
                {
                    "decision": "rejected_by_firefly",
                    "ok": False,
                    "mode": "quantoz_eurd_mainnet_transfer",
                    "paymentApprovalHash": payment_hash,
                    "receiver": request["receiver"],
                    "amountAtomic": str(request["amountAtomic"]),
                    "amount": _format_eurd_amount(request["amountAtomic"]),
                    "asset": "EURD",
                    "assetId": str(EURD_ASA_ID),
                    "network": EURD_NETWORK,
                    "firefly": approval,
                    "telegramText": "❌ EURD payment canceled on Firefly. No payment was made.",
                },
                400,
            )

        if str(approval.get("approvedHash", "")).lower() != payment_hash:
            raise ValueError("Firefly approved hash does not match EURD payment hash.")

        note = f"sign402-eurd:{payment_hash[:16]}".encode("utf-8")
        payment = self.server.eurd_payment_executor(
            receiver=request["receiver"],
            amount_atomic=request["amountAtomic"],
            note=note,
        )
        tx_id = str(payment["txId"])
        tx_url = _transaction_display_url(tx_id, network="mainnet")
        return (
            {
                "decision": "approved_and_executed",
                "ok": True,
                "mode": "quantoz_eurd_mainnet_transfer",
                "paymentApprovalHash": payment_hash,
                "paymentCommitment": request["paymentCommitment"],
                "receiver": request["receiver"],
                "amountAtomic": str(request["amountAtomic"]),
                "amount": _format_eurd_amount(request["amountAtomic"]),
                "asset": "EURD",
                "assetId": str(EURD_ASA_ID),
                "network": EURD_NETWORK,
                "txId": tx_id,
                "txUrl": tx_url,
                "payment": payment,
                "firefly": approval,
                "telegramText": (
                    f"✅ EURD paid: {_format_eurd_amount(request['amountAtomic'])}. "
                    f"Tx {tx_url}."
                ),
            },
            200,
        )

    def _handle_agent_inspect_x402(self) -> None:
        try:
            payload = self._read_json()
            resource_url = str(payload.get("url", "")).strip()
            if not resource_url:
                raise ValueError("url is required")
            _validate_external_resource_url(resource_url)

            policy_hash = self._policy_hash_from_payload_or_state(payload)
            result = self.server.x402_inspector(resource_url, policy_hash)
            self._send_json(result)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)

    def _handle_agent_buy_x402(self) -> None:
        if not self._acquire_firefly():
            self._send_json(_busy_payload(), status=409)
            return

        try:
            payload = self._read_json()
            resource_url = str(payload.get("url", "")).strip()
            if not resource_url:
                raise ValueError("url is required")
            _validate_external_resource_url(resource_url)

            result = self.server.x402_buyer(resource_url)
            self._send_json(result)
        except TimeoutError:
            self._send_json(_firefly_timeout_payload(decision=True), status=504)
        except Exception as exc:
            self._send_json({"decision": "rejected", "ok": False, "error": str(exc)}, status=400)
        finally:
            self._release_firefly()

    def _policy_hash_from_payload_or_state(self, payload: dict[str, Any]) -> str:
        if payload.get("policyHash"):
            return _read_hash(payload, "policyHash")

        policy_state = self.server.agent_state_store.read_policy()
        if policy_state is None:
            raise ValueError("policyHash is required when no policy is stored")
        policy_hash = str(policy_state.get("policyHash", "")).lower()
        if not HEX_32_RE.fullmatch(policy_hash):
            raise ValueError("stored policyHash must be 64 hex characters")
        return policy_hash

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0:
            raise ValueError("Content-Length must not be negative")
        if length > MAX_REQUEST_BODY_BYTES:
            raise ValueError("request body is too large")
        body = self.rfile.read(length)
        if not body:
            raise ValueError("request body is empty")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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

    def _read_rejected_tool_retry(
        self,
        tool: dict[str, Any],
        request_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        cache = getattr(self.server, "rejected_tool_retry_cache", None)
        if not isinstance(cache, dict):
            return None

        cache_key = _tool_retry_cache_key(tool, request_context)
        cached = cache.get(cache_key)
        if not isinstance(cached, dict):
            return None

        if time.time() - float(cached.get("storedAt", 0)) > REJECTED_TOOL_RETRY_SUPPRESSION_SECONDS:
            cache.pop(cache_key, None)
            return None

        response = dict(cached.get("response") or {})
        response["duplicateSuppressed"] = True
        response["message"] = (
            "Previous Firefly cancel for this same request was not retried. "
            "Ask again with a new request if you want to purchase."
        )
        return response

    def _store_rejected_tool_retry(
        self,
        tool: dict[str, Any],
        request_context: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        cache = getattr(self.server, "rejected_tool_retry_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.server.rejected_tool_retry_cache = cache

        cache[_tool_retry_cache_key(tool, request_context)] = {
            "storedAt": time.time(),
            "response": dict(response),
        }


class Sign402GatewayServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        handler_class,
        *,
        firefly: FireflyClient,
        payment_executor: Callable[[dict[str, Any], str], dict[str, Any]],
        event_store: "LatestEventStore",
        agent_state_store: "AgentStateStore",
        agent_buy_probe: Callable[[str], dict[str, Any]],
        x402_inspector: Callable[[str, str], dict[str, Any]],
        x402_buyer: Callable[..., dict[str, Any]],
        eurd_payment_executor: Callable[..., dict[str, Any]],
    ):
        super().__init__(server_address, handler_class)
        self.firefly = firefly
        self.payment_executor = payment_executor
        self.event_store = event_store
        self.agent_state_store = agent_state_store
        self.agent_buy_probe = agent_buy_probe
        self.x402_inspector = x402_inspector
        self.x402_buyer = x402_buyer
        self.eurd_payment_executor = eurd_payment_executor
        self.firefly_lock = threading.Lock()
        self.rejected_tool_retry_cache: dict[str, dict[str, Any]] = {}


def build_server(
    host: str,
    port: int,
    *,
    firefly_port: str,
    payment_executor_dir: Path = PAYMENT_EXECUTOR_DIR,
    event_store_path: Path = DEFAULT_EVENT_STORE_PATH,
    agent_state_path: Path = DEFAULT_AGENT_STATE_PATH,
    resource_base_url: str = "http://127.0.0.1:8090",
) -> Sign402GatewayServer:
    firefly = FireflyClient(port=firefly_port)
    payment_executor = build_payment_executor(payment_executor_dir)
    x402_payment_signature_builder = build_x402_payment_signature_builder(payment_executor_dir)
    event_store = LatestEventStore(event_store_path)
    agent_state_store = AgentStateStore(agent_state_path)
    x402_inspector = ExternalX402Inspector()
    eurd_payment_executor = build_eurd_payment_executor()
    x402_buyer = ExternalX402Buyer(
        firefly=firefly,
        payment_signature_builder=x402_payment_signature_builder,
        event_store=event_store,
        agent_state_store=agent_state_store,
    )
    agent_buy_probe = AgentBuyProbeRunner(
        firefly=firefly,
        payment_executor=payment_executor,
        event_store=event_store,
        agent_state_store=agent_state_store,
        resource_base_url=resource_base_url,
    )
    return Sign402GatewayServer(
        (host, port),
        Sign402GatewayHandler,
        firefly=firefly,
        payment_executor=payment_executor,
        event_store=event_store,
        agent_state_store=agent_state_store,
        agent_buy_probe=agent_buy_probe,
        x402_inspector=x402_inspector,
        x402_buyer=x402_buyer,
        eurd_payment_executor=eurd_payment_executor,
    )


def build_payment_executor(payment_executor_dir: Path):
    from algosdk.v2client.algod import AlgodClient

    env = _read_env(payment_executor_dir / ".env")
    algod_client = AlgodClient("", env.get("ALGOD_URL", "https://testnet-api.algonode.cloud"))
    sender = env["ALGORAND_SENDER"]
    private_key = env["ALGORAND_PRIVATE_KEY"]

    def pay(requirement: dict[str, Any], policy_hash: str) -> dict[str, Any]:
        return execute_payment(
            algod_client=algod_client,
            sender=sender,
            private_key=private_key,
            payment_request=requirement,
            policy_hash=policy_hash,
        )

    return pay


def build_x402_payment_signature_builder(payment_executor_dir: Path):
    env = _read_env(payment_executor_dir / ".env")
    sender = env["ALGORAND_SENDER"]
    private_key = env["ALGORAND_PRIVATE_KEY"]
    algod_urls = _dedupe_strings(
        [
            env.get("ALGOD_URL", ""),
            *str(env.get("ALGOD_FALLBACK_URLS", "")).split(","),
            *DEFAULT_TESTNET_ALGOD_URLS,
        ]
    )

    def build_signature(payment_required: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        for algod_url in algod_urls:
            try:
                return build_x402_avm_payment_signature_header(
                    payment_required=payment_required,
                    sender=sender,
                    private_key=private_key,
                    algod_url=algod_url,
                )
            except Exception as exc:
                if not _is_temporary_x402_payment_error(exc):
                    raise
                errors.append(f"{algod_url}: {type(exc).__name__}: {exc}")
        raise RuntimeError("x402 payment signature failed on all algod endpoints: " + " | ".join(errors))

    return build_signature


def build_eurd_payment_executor(wallet_env_path: Path | None = None):
    path = wallet_env_path or Path(os.getenv("QUANTOZ_WALLET_ENV", DEFAULT_QUANTOZ_WALLET_ENV_PATH))
    if not path.exists():
        def unavailable_pay(*, receiver: str, amount_atomic: int, note: bytes | None = None) -> dict[str, Any]:
            raise RuntimeError(
                f"Quantoz EURD wallet env not found at {path}. Set QUANTOZ_WALLET_ENV to enable /agent/pay-eurd."
            )

        return unavailable_pay

    env = _read_env(path)
    algod_urls = _dedupe_strings(
        [
            env.get("ALGOD_URL", ""),
            *str(env.get("ALGOD_FALLBACK_URLS", "")).split(","),
            *DEFAULT_MAINNET_ALGOD_URLS,
        ]
    )
    sender = env.get("ALGORAND_MAINNET_ADDRESS") or env.get("ALGORAND_SENDER")
    private_key = env["ALGORAND_PRIVATE_KEY"]
    if not sender:
        raise ValueError("Quantoz wallet env must include ALGORAND_MAINNET_ADDRESS or ALGORAND_SENDER")

    def pay(*, receiver: str, amount_atomic: int, note: bytes | None = None) -> dict[str, Any]:
        errors: list[str] = []
        for algod_url in algod_urls:
            try:
                return _execute_eurd_asset_transfer(
                    algod_url=algod_url,
                    sender=sender,
                    private_key=private_key,
                    receiver=receiver,
                    amount_atomic=amount_atomic,
                    note=note,
                )
            except Exception as exc:
                errors.append(f"{algod_url}: {type(exc).__name__}: {exc}")
        raise RuntimeError("EURD broadcast failed on all algod endpoints: " + " | ".join(errors))

    return pay


def _execute_eurd_asset_transfer(
    *,
    algod_url: str,
    sender: str,
    private_key: str,
    receiver: str,
    amount_atomic: int,
    note: bytes | None = None,
) -> dict[str, Any]:
    from algosdk.encoding import msgpack_encode
    from algosdk.transaction import AssetTransferTxn
    from algosdk.v2client.algod import AlgodClient

    algod_client = AlgodClient("", algod_url)
    if amount_atomic <= 0:
        raise ValueError("amount_atomic must be positive")
    if not receiver:
        raise ValueError("receiver is required")

    tx = AssetTransferTxn(
        sender=sender,
        sp=algod_client.suggested_params(),
        receiver=receiver,
        amt=int(amount_atomic),
        index=EURD_ASA_ID,
        note=note,
    )
    signed_tx = tx.sign(private_key)
    raw_txn = base64.b64decode(msgpack_encode(signed_tx))
    tx_id = _broadcast_raw_transaction(algod_url, raw_txn)
    return {
        "txId": tx_id,
        "network": EURD_NETWORK,
        "receiver": receiver,
        "amountAtomic": str(int(amount_atomic)),
        "asset": "EURD",
        "assetId": str(EURD_ASA_ID),
        "note": note.decode("utf-8") if note else "",
        "algodUrl": algod_url,
    }


def _broadcast_raw_transaction(algod_url: str, raw_txn: bytes) -> str:
    url = algod_url.rstrip("/") + "/v2/transactions"
    request = urllib.request.Request(
        url,
        data=raw_txn,
        method="POST",
        headers={
            "Content-Type": "application/x-binary",
            "Accept": "application/json",
            "User-Agent": "Hermes-Sign402/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc

    tx_id = payload.get("txId")
    if not tx_id:
        raise RuntimeError(f"Algod broadcast response missing txId: {payload}")
    return str(tx_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified local gateway for Hermes Sign402.")
    parser.add_argument("--host", default=os.getenv("SIGN402_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SIGN402_GATEWAY_PORT", "8099")))
    parser.add_argument("--firefly-port", default=os.getenv("FIREFLY_PORT"))
    parser.add_argument(
        "--payment-executor-dir",
        type=Path,
        default=Path(os.getenv("SIGN402_PAYMENT_EXECUTOR_DIR", PAYMENT_EXECUTOR_DIR)),
    )
    parser.add_argument(
        "--event-store-path",
        type=Path,
        default=Path(os.getenv("SIGN402_EVENT_STORE_PATH", DEFAULT_EVENT_STORE_PATH)),
    )
    parser.add_argument(
        "--agent-state-path",
        type=Path,
        default=Path(os.getenv("SIGN402_AGENT_STATE_PATH", DEFAULT_AGENT_STATE_PATH)),
    )
    parser.add_argument(
        "--resource-base-url",
        default=os.getenv("SIGN402_RESOURCE_BASE_URL", "http://127.0.0.1:8090"),
    )
    args = parser.parse_args()

    firefly_port = args.firefly_port or find_firefly_port()
    server = build_server(
        args.host,
        args.port,
        firefly_port=firefly_port,
        payment_executor_dir=args.payment_executor_dir,
        event_store_path=args.event_store_path,
        agent_state_path=args.agent_state_path,
        resource_base_url=args.resource_base_url,
    )

    print(f"Sign402 gateway listening on http://{args.host}:{args.port}")
    print(f"Firefly port: {firefly_port}")
    print(f"Payment executor dir: {args.payment_executor_dir}")
    print(f"Event store path: {args.event_store_path}")
    print(f"Agent state path: {args.agent_state_path}")
    print(f"Resource base URL: {args.resource_base_url}")
    server.serve_forever()


class AgentBuyProbeRunner:
    def __init__(
        self,
        *,
        firefly: FireflyClient,
        payment_executor: Callable[[dict[str, Any], str], dict[str, Any]],
        event_store: "LatestEventStore",
        agent_state_store: "AgentStateStore",
        resource_base_url: str,
    ):
        self.firefly = firefly
        self.payment_executor = payment_executor
        self.event_store = event_store
        self.agent_state_store = agent_state_store
        self.resource_client = X402ResourceClient(resource_base_url)

    def __call__(self, target: str) -> dict[str, Any]:
        policy_state = self.agent_state_store.read_policy()
        if policy_state is None:
            raise ValueError("No Firefly-approved policy stored. Call /approve-policy first.")

        policy = policy_state["policy"]
        policy_hash = str(policy_state["policyHash"]).lower()
        approved_hash = str(policy_state["firefly"]["approvedHash"]).lower()
        if policy_hash != approved_hash:
            raise ValueError("Stored policy hash does not match Firefly approval.")

        first_response = self.resource_client.get_probe_without_payment(target)
        if first_response.get("status") != 402:
            raise ValueError("Expected x402 resource server to return 402 Payment Required.")

        requirement = first_response["paymentRequirements"]
        self.agent_state_store.validate_policy_allows(policy, policy_hash, requirement)

        payment_commitment = build_payment_commitment(requirement, policy_hash)
        payment_hash = payment_commitment["paymentHash"]
        approval = self.firefly.approve_payment_hash(
            payment_hash,
            context_lines=_payment_context_lines(requirement),
        )
        if not approval.get("approved"):
            event = {
                "decision": "rejected_by_firefly",
                "target": target,
                "policyHash": policy_hash,
                "paymentApprovalHash": payment_hash,
                "paymentRequirements": requirement,
                "firefly": approval,
            }
            self.event_store.write(event)
            return event

        if str(approval.get("approvedHash", "")).lower() != payment_hash:
            raise ValueError("Firefly approved hash does not match payment commitment hash.")

        payment = self.payment_executor(requirement, policy_hash)
        self.agent_state_store.record_payment(
            policy_hash,
            requirement["paymentIntent"],
            int(str(requirement["amountAtomic"])),
        )

        payment_proof = {
            "verificationMode": "algorand",
            "txId": payment["txId"],
            "network": requirement["network"],
            "receiver": requirement["receiver"],
            "amountAtomic": requirement["amountAtomic"],
            "asset": requirement["asset"],
            "resource": requirement["resource"],
            "paymentIntent": requirement["paymentIntent"],
            "policyHash": policy_hash,
            "paymentApprovalHash": payment_hash,
        }
        encoded_payment = encode_payment_proof(payment_proof)
        resource_result = self._retry_paid_resource(target, encoded_payment)

        decision = "approved_and_executed"
        if resource_result.get("status") == 402 or resource_result.get("error"):
            decision = "payment_sent_access_denied"

        event = {
            "decision": decision,
            "target": target,
            "policyHash": policy_hash,
            "paymentApprovalHash": payment_hash,
            "txId": payment["txId"],
            "resource": requirement["resource"],
            "paymentIntent": requirement["paymentIntent"],
            "amountAtomic": requirement["amountAtomic"],
            "asset": requirement["asset"],
            "network": requirement["network"],
            "deviceModel": approval.get("deviceModel"),
            "deviceSerial": approval.get("deviceSerial"),
            "remainingBudgetAtomic": str(self.agent_state_store.remaining_budget(policy_hash)),
            "paymentRequirements": requirement,
            "paymentCommitment": payment_commitment["commitment"],
            "payment": payment,
            "paymentProof": payment_proof,
            "resourceResult": resource_result,
            "result": resource_result.get("result"),
        }
        self.event_store.write(event)
        return event

    def _retry_paid_resource(self, target: str, encoded_payment: str) -> dict[str, Any]:
        last_response: dict[str, Any] = {}
        for attempt in range(8):
            last_response = self.resource_client.get_probe_with_payment(target, encoded_payment)
            if last_response.get("status") != 402 and not last_response.get("error"):
                return last_response
            if attempt < 7:
                time.sleep(2)
        return last_response


class ExternalX402Inspector:
    def __call__(self, resource_url: str, policy_hash: str) -> dict[str, Any]:
        payload = fetch_x402_payment_required(resource_url)
        requirement = normalize_x402_payment_required(payload, resource_url=resource_url)
        payment_commitment = build_payment_commitment(requirement, policy_hash)
        return {
            "ok": True,
            "mode": "inspect_only",
            "resourceUrl": resource_url,
            "source": "goplausible-x402",
            "rawPaymentRequired": payload,
            "paymentRequirements": requirement,
            "paymentCommitment": payment_commitment,
            "nextStep": "Use x402-avm to build official X-PAYMENT paymentGroup before executing.",
        }


class ExternalX402Buyer:
    def __init__(
        self,
        *,
        firefly: FireflyClient,
        payment_signature_builder: Callable[[dict[str, Any]], dict[str, Any]],
        event_store: "LatestEventStore",
        agent_state_store: "AgentStateStore",
    ):
        self.firefly = firefly
        self.payment_signature_builder = payment_signature_builder
        self.event_store = event_store
        self.agent_state_store = agent_state_store

    def __call__(
        self,
        resource_url: str,
        *,
        firefly_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy_state = self.agent_state_store.read_policy()
        if policy_state is None:
            raise ValueError("No Firefly-approved policy stored. Call /approve-policy first.")

        policy = policy_state["policy"]
        policy_hash = str(policy_state["policyHash"]).lower()
        approved_hash = str(policy_state["firefly"]["approvedHash"]).lower()
        if policy_hash != approved_hash:
            raise ValueError("Stored policy hash does not match Firefly approval.")

        raw_payment_required = fetch_x402_payment_required(resource_url)
        requirement = normalize_x402_payment_required(raw_payment_required, resource_url=resource_url)
        self.agent_state_store.validate_policy_allows(policy, policy_hash, requirement)

        payment_commitment = build_payment_commitment(requirement, policy_hash)
        payment_hash = payment_commitment["paymentHash"]
        approval = self.firefly.approve_payment_hash(
            payment_hash,
            context_lines=_payment_context_lines(requirement, firefly_context),
        )
        if not approval.get("approved"):
            event = {
                "decision": "rejected_by_firefly",
                "ok": False,
                "resourceUrl": resource_url,
                "policyHash": policy_hash,
                "paymentApprovalHash": payment_hash,
                "paymentRequirements": requirement,
                "firefly": approval,
            }
            self.event_store.write(event)
            return event

        if str(approval.get("approvedHash", "")).lower() != payment_hash:
            raise ValueError("Firefly approved hash does not match payment commitment hash.")

        resource_result = _fetch_x402_paid_resource_with_retry(
            resource_url,
            payment_signature_builder=lambda: self.payment_signature_builder(raw_payment_required),
        )
        if int(resource_result.get("status", 0)) != 200:
            raise ValueError(f"Official x402 resource denied payment: {resource_result}")

        payment_response = resource_result.get("paymentResponse", {})
        tx_id = payment_response.get("transaction")
        self.agent_state_store.record_payment(
            policy_hash,
            requirement["paymentIntent"],
            int(str(requirement["amountAtomic"])),
        )

        event = {
            "decision": "approved_and_executed",
            "ok": True,
            "mode": "official_x402_avm",
            "resourceUrl": resource_url,
            "policyHash": policy_hash,
            "paymentApprovalHash": payment_hash,
            "txId": tx_id,
            "paymentIntent": requirement["paymentIntent"],
            "amountAtomic": requirement["amountAtomic"],
            "asset": requirement["asset"],
            "network": requirement["network"],
            "x402Network": requirement.get("x402Network"),
            "receiver": requirement["receiver"],
            "deviceModel": approval.get("deviceModel"),
            "deviceSerial": approval.get("deviceSerial"),
            "remainingBudgetAtomic": str(self.agent_state_store.remaining_budget(policy_hash)),
            "paymentRequirements": requirement,
            "paymentCommitment": payment_commitment["commitment"],
            "paymentResponse": payment_response,
            "resourceResult": resource_result,
            "result": "official_x402_resource_access_granted",
        }
        self.event_store.write(event)
        return event


def _fetch_x402_paid_resource_with_retry(
    resource_url: str,
    *,
    payment_signature_builder: Callable[[], dict[str, Any]],
    max_attempts: int = 3,
    retry_delay_seconds: float = 2.0,
) -> dict[str, Any]:
    last_result: dict[str, Any] = {}
    for attempt in range(max_attempts):
        try:
            payment_signature = payment_signature_builder()
        except Exception as exc:
            if not _is_temporary_x402_payment_error(exc) or attempt >= max_attempts - 1:
                raise
            time.sleep(retry_delay_seconds)
            continue

        last_result = fetch_x402_paid_resource(
            resource_url,
            payment_signature_header=payment_signature["headerValue"],
        )
        status = int(last_result.get("status", 0))
        if status == 200:
            return last_result
        if status not in {402, 403, 404}:
            return last_result
        if attempt < max_attempts - 1:
            time.sleep(retry_delay_seconds)
    return last_result


def _is_temporary_x402_payment_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "403" in message
        or "forbidden" in message
        or "temporar" in message
        or "rate limit" in message
        or type(error).__name__ in {"AlgodHTTPError", "HTTPError", "URLError"}
    )


class LatestEventStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def read(self) -> dict[str, Any] | None:
        with self.lock:
            if not self.path.exists():
                return None
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("event store must contain a JSON object")
            return payload

    def write(self, event: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(event, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
            return event


class AgentStateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def read_policy(self) -> dict[str, Any] | None:
        state = self._read_state()
        policy_state = state.get("policyApproval")
        if isinstance(policy_state, dict):
            return policy_state
        return None

    def write_policy(self, policy_approval: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            state = {
                "policyApproval": policy_approval,
                "spentAtomic": "0",
                "usedPaymentIntents": [],
                "approvedPaymentHashes": {},
            }
            self._write_state_unlocked(state)
            return policy_approval

    def record_payment_approval(
        self,
        payment_hash: str,
        approval: dict[str, Any],
    ) -> None:
        with self.lock:
            state = self._read_state_unlocked()
            approved_hashes = state.get("approvedPaymentHashes", {})
            if not isinstance(approved_hashes, dict):
                approved_hashes = {}
            approved_hashes[payment_hash.lower()] = {
                "approvedHash": str(approval.get("approvedHash", "")).lower(),
                "deviceModel": approval.get("deviceModel"),
                "deviceSerial": approval.get("deviceSerial"),
            }
            state["approvedPaymentHashes"] = approved_hashes
            self._write_state_unlocked(state)

    def consume_payment_approval(self, payment_hash: str) -> bool:
        with self.lock:
            state = self._read_state_unlocked()
            approved_hashes = state.get("approvedPaymentHashes", {})
            if not isinstance(approved_hashes, dict):
                return False

            approval = approved_hashes.get(payment_hash.lower())
            if not isinstance(approval, dict):
                return False
            if str(approval.get("approvedHash", "")).lower() != payment_hash.lower():
                return False

            del approved_hashes[payment_hash.lower()]
            state["approvedPaymentHashes"] = approved_hashes
            self._write_state_unlocked(state)
            return True

    def validate_policy_allows(
        self,
        policy: dict[str, Any],
        policy_hash: str,
        requirement: dict[str, Any],
    ) -> None:
        state = self._read_state()
        if policy_hash != str(state.get("policyApproval", {}).get("policyHash", "")).lower():
            raise ValueError("Policy hash does not match stored policy.")

        amount = int(str(requirement["amountAtomic"]))
        max_per_payment = int(str(policy["maxPerPaymentAtomic"]))
        max_budget = int(str(policy["maxBudgetAtomic"]))
        spent = int(str(state.get("spentAtomic", "0")))
        used_intents = set(state.get("usedPaymentIntents", []))
        payment_intent = str(requirement["paymentIntent"])

        if str(requirement.get("network")) != "algorand-testnet":
            raise ValueError("Only algorand-testnet payments are allowed")
        if payment_intent in used_intents:
            raise ValueError("paymentIntent already used")
        if amount > max_per_payment:
            raise ValueError("amountAtomic exceeds maxPerPaymentAtomic")
        if spent + amount > max_budget:
            raise ValueError("amountAtomic exceeds remaining budget")
        if str(requirement["asset"]) != str(policy["asset"]):
            raise ValueError("asset does not match policy.asset")
        if str(requirement.get("purpose")) != str(policy["allowedPurpose"]):
            raise ValueError("purpose does not match policy.allowedPurpose")

    def record_payment(self, policy_hash: str, payment_intent: str, amount_atomic: int) -> None:
        with self.lock:
            state = self._read_state_unlocked()
            if policy_hash != str(state.get("policyApproval", {}).get("policyHash", "")).lower():
                raise ValueError("Policy hash does not match stored policy.")

            used_intents = list(state.get("usedPaymentIntents", []))
            if payment_intent not in used_intents:
                used_intents.append(payment_intent)
            spent = int(str(state.get("spentAtomic", "0"))) + amount_atomic
            state["usedPaymentIntents"] = used_intents
            state["spentAtomic"] = str(spent)
            self._write_state_unlocked(state)

    def remaining_budget(self, policy_hash: str) -> int:
        state = self._read_state()
        policy_approval = state.get("policyApproval", {})
        if policy_hash != str(policy_approval.get("policyHash", "")).lower():
            return 0
        policy = policy_approval.get("policy", {})
        max_budget = int(str(policy.get("maxBudgetAtomic", "0")))
        spent = int(str(state.get("spentAtomic", "0")))
        return max(0, max_budget - spent)

    def _read_state(self) -> dict[str, Any]:
        with self.lock:
            return self._read_state_unlocked()

    def _read_state_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("agent state must contain a JSON object")
        return payload

    def _write_state_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)


def _read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value.strip().strip('"')
    return env


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _read_hash(payload: dict[str, Any], key: str) -> str:
    value = str(payload[key]).lower()
    if not HEX_32_RE.fullmatch(value):
        raise ValueError(f"{key} must be 64 hex characters")
    return value


def _payment_context_lines(
    requirement: dict[str, Any] | None,
    display_context: dict[str, Any] | None = None,
) -> list[str]:
    if not requirement or "amountAtomic" not in requirement:
        return ["x402 PAYMENT", "sign402 approval"]

    resource = str(requirement.get("resource", ""))
    display_context = display_context or {}
    title = str(
        display_context.get("title")
        or ("x402 WEATHER" if "weather" in resource.lower() else "x402 PAYMENT")
    )
    service = str(
        display_context.get("service")
        or ("GoPlausible API" if "goplausible" in resource.lower() else "x402 API")
    )
    return [
        title,
        _format_display_amount(requirement),
        service,
    ]


def _format_display_amount(requirement: dict[str, Any]) -> str:
    amount_atomic = int(str(requirement.get("amountAtomic", "0")))
    asset = str(requirement.get("asset", ""))
    extra = requirement.get("extra")
    asset_name = ""
    decimals = 0
    if isinstance(extra, dict):
        asset_name = str(extra.get("name", ""))
        decimals = int(str(extra.get("decimals", "0")))

    if asset == "10458941" and not asset_name:
        asset_name = "USDC"
        decimals = 6
    elif asset == "ALGO_TEST":
        asset_name = "ALGO"
        decimals = 6
    elif not asset_name:
        asset_name = asset

    if decimals <= 0:
        return f"{amount_atomic} {asset_name}"

    divisor = 10**decimals
    whole = amount_atomic // divisor
    fraction = amount_atomic % divisor
    fraction_text = str(fraction).zfill(decimals).rstrip("0")
    if not fraction_text:
        return f"{whole} {asset_name}"
    return f"{whole}.{fraction_text} {asset_name}"


def _validate_payment_requirements(requirement: Any) -> None:
    if not isinstance(requirement, dict):
        raise ValueError("paymentRequirements must be an object")
    if requirement.get("network") != "algorand-testnet":
        raise ValueError("Only algorand-testnet is supported")
    if requirement.get("asset") != "ALGO_TEST":
        raise ValueError("Only ALGO_TEST is supported")
    if not requirement.get("receiver"):
        raise ValueError("paymentRequirements.receiver is required")
    if not requirement.get("paymentIntent"):
        raise ValueError("paymentRequirements.paymentIntent is required")
    amount = int(str(requirement.get("amountAtomic", "0")))
    if amount <= 0:
        raise ValueError("paymentRequirements.amountAtomic must be positive")


def _eurd_payment_request(payload: dict[str, Any]) -> dict[str, Any]:
    receiver = str(
        payload.get("receiver")
        or payload.get("to")
        or payload.get("payTo")
        or ""
    ).strip()
    if not receiver:
        raise ValueError("receiver is required")

    amount_atomic = _parse_eurd_amount(payload)
    if amount_atomic <= 0:
        raise ValueError("EURD amount must be positive")
    if amount_atomic > EURD_MAX_AMOUNT_ATOMIC:
        raise ValueError(
            f"EURD amount exceeds demo max of {_format_eurd_amount(EURD_MAX_AMOUNT_ATOMIC)}"
        )

    memo = str(payload.get("memo") or payload.get("message") or "Hermes Sign402 EURD payment").strip()
    commitment = {
        "type": "sign402-eurd-payment",
        "network": EURD_NETWORK,
        "asset": "EURD",
        "assetId": str(EURD_ASA_ID),
        "assetDecimals": EURD_ASSET_DECIMALS,
        "amountAtomic": str(amount_atomic),
        "receiver": receiver,
        "memo": memo[:160],
    }
    return {
        "receiver": receiver,
        "amountAtomic": amount_atomic,
        "memo": memo,
        "paymentCommitment": commitment,
    }


def _parse_eurd_amount(payload: dict[str, Any]) -> int:
    if payload.get("amountAtomic") is not None:
        try:
            return int(str(payload["amountAtomic"]))
        except ValueError as exc:
            raise ValueError("amountAtomic must be an integer") from exc

    raw_amount = str(payload.get("amount") or payload.get("eurd") or "").strip()
    if not raw_amount:
        raise ValueError("amount or amountAtomic is required")
    normalized = raw_amount.removesuffix("EURD").removesuffix("eurd").strip()
    if not re.fullmatch(r"\d+(\.\d{1,2})?", normalized):
        raise ValueError("EURD amount must have at most 2 decimal places")
    whole, _, fraction = normalized.partition(".")
    return int(whole) * (10**EURD_ASSET_DECIMALS) + int(fraction.ljust(EURD_ASSET_DECIMALS, "0") or "0")


def _format_eurd_amount(amount_atomic: int) -> str:
    whole = amount_atomic // (10**EURD_ASSET_DECIMALS)
    fraction = amount_atomic % (10**EURD_ASSET_DECIMALS)
    return f"{whole}.{str(fraction).zfill(EURD_ASSET_DECIMALS)} EURD"


def _hash_json(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _short_address(address: str) -> str:
    if len(address) <= 16:
        return address
    return f"{address[:8]}...{address[-6:]}"


def _resolve_paid_tool(payload: dict[str, Any]) -> dict[str, Any]:
    raw_tool = str(
        payload.get("tool")
        or payload.get("toolId")
        or payload.get("name")
        or payload.get("mcpTool")
        or ""
    ).strip()
    if not raw_tool:
        raise ValueError("tool is required")

    lookup = raw_tool.lower()
    tool_id = PAID_TOOL_ALIASES.get(lookup, lookup)
    tool = PAID_TOOLS.get(tool_id)
    if tool is None:
        available = ", ".join(sorted(PAID_TOOLS))
        raise ValueError(f"Unknown paid tool '{raw_tool}'. Available tools: {available}")
    return dict(tool)


def _tool_request_context(payload: dict[str, Any]) -> dict[str, Any]:
    city = str(payload.get("city") or payload.get("location") or "").strip()
    qr_data = str(
        payload.get("url")
        or payload.get("text")
        or payload.get("data")
        or payload.get("target")
        or ""
    ).strip()
    context: dict[str, Any] = {}
    if city:
        context["city"] = city
    if qr_data:
        context["qrData"] = qr_data
    for key in ("receiver", "to", "payTo", "amount", "amountAtomic", "memo", "message"):
        if payload.get(key) is not None:
            context[key] = payload[key]
    return context


def _tool_retry_cache_key(tool: dict[str, Any], request_context: dict[str, Any]) -> str:
    return json.dumps(
        {
            "toolId": tool.get("id"),
            "requestContext": request_context,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_tool_request(tool: dict[str, Any], request_context: dict[str, Any]) -> None:
    if tool.get("id") == "quantoz.eurd.transfer":
        _eurd_payment_request(request_context)
        return
    if tool.get("id") != "sign402.qr":
        return
    qr_data = str(request_context.get("qrData") or "")
    if not qr_data:
        raise ValueError("qr tool requires url, text, data, or target")
    if len(qr_data) > MAX_QR_DATA_CHARS:
        raise ValueError(
            f"qr payload must be at most {MAX_QR_DATA_CHARS} characters"
        )


def _tool_payment_resource_url(tool: dict[str, Any]) -> str:
    return str(tool.get("paymentResourceUrl") or tool["resourceUrl"])


def _validate_external_resource_url(resource_url: str) -> None:
    parsed = urlparse(resource_url)
    if parsed.scheme.lower() != "https":
        raise ValueError("external x402 resource URL must use https")
    if parsed.username or parsed.password:
        raise ValueError("external x402 resource URL must not include credentials")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError("external x402 resource URL must include a hostname")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValueError("external x402 resource URL must not target localhost")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("external x402 resource URL must use a public IP address")


def _agent_manifest() -> dict[str, Any]:
    return {
        "name": "Hermes Sign402 Gateway",
        "description": "Hardware-approved x402 paid tools for agentic commerce on Algorand.",
        "x402Version": 2,
        "network": "algorand-testnet",
        "paymentStandard": "x402",
        "defaultRail": "algorand-testnet-usdc",
        "paymentRails": list(PAYMENT_RAILS.values()),
        "tools": [_manifest_tool(tool) for tool in PAID_TOOLS.values()],
        "security": {
            "agentPrivateKeyAccess": False,
            "policyApproval": "Firefly required",
            "paymentApproval": "Firefly required",
            "budgetEnforcement": "gateway policy store",
            "replayProtection": "paymentIntent tracking",
            "privateKeyLocation": "local payment executor only",
            "future": [
                "Quantoz EURD mainnet rail",
                "ARC-90 exact top-ups",
                "ARC-58 scoped account abstraction",
            ],
        },
        "endpoints": {
            "listTools": "/agent/tools",
            "listPaymentRails": "/agent/rails",
            "inspectTool": "/agent/inspect-tool",
            "buyTool": "/agent/buy-tool",
            "payEurd": "/agent/pay-eurd",
            "latestEvent": "/events/latest",
        },
        "directPayments": [
            {
                "id": "quantoz.eurd.transfer",
                "name": "Quantoz EURD Transfer",
                "rail": "quantoz-eurd-mainnet",
                "network": EURD_NETWORK,
                "asset": "EURD",
                "assetId": str(EURD_ASA_ID),
                "assetDecimals": EURD_ASSET_DECIMALS,
                "endpoint": "/agent/pay-eurd",
                "requiresFireflyApproval": True,
                "receiptField": "telegramText",
            }
        ],
    }


def _agent_rails() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "payment_rail_catalog",
        "defaultRail": "algorand-testnet-usdc",
        "rails": list(PAYMENT_RAILS.values()),
        "note": "Quantoz EURD is exposed as an optional live mainnet transfer rail through POST /agent/pay-eurd. The default paid tools stay on TestNet USDC.",
    }


def _manifest_tool(tool: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "id": tool["id"],
        "name": tool["name"],
        "description": tool["description"],
        "kind": tool["kind"],
        "source": tool["source"],
        "resourceUrl": tool["resourceUrl"],
        "paymentResourceUrl": _tool_payment_resource_url(tool),
        "mcpStyleName": tool["mcpStyleName"],
        "inputSchema": tool["inputSchema"],
        "paymentStandard": tool.get("paymentStandard", "x402"),
        "network": tool.get("network", "algorand-testnet"),
        "asset": tool.get("asset", "10458941"),
        "assetName": tool.get("assetName", "USDC"),
        "price": tool.get("price", "0.01 USDC"),
        "priceAtomic": tool.get("priceAtomic", "10000"),
        "requiresFireflyApproval": True,
        "inspectEndpoint": tool.get("inspectEndpoint", "/agent/inspect-tool"),
        "buyEndpoint": tool.get("buyEndpoint", "/agent/buy-tool"),
        "receiptField": "telegramText",
    }
    return manifest


def _tool_result(
    tool: dict[str, Any],
    payload: dict[str, Any],
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(payload)
    request_context = request_context or {}
    result["tool"] = {
        "id": tool["id"],
        "name": tool["name"],
        "kind": tool["kind"],
        "source": tool["source"],
        "description": tool["description"],
        "resourceUrl": tool["resourceUrl"],
        "paymentResourceUrl": _tool_payment_resource_url(tool),
        "mcpStyleName": tool["mcpStyleName"],
        "inputSchema": tool["inputSchema"],
    }
    result["toolId"] = tool["id"]
    result["toolName"] = tool["name"]
    result["command"] = tool["command"]
    result["mode"] = "paid_tool_" + str(payload.get("mode", "x402"))
    result.update(request_context)
    if result.get("decision") == "rejected_by_firefly" and not result.get("telegramText"):
        result["telegramText"] = "❌ Purchase canceled on Firefly. No payment was made."
    summary = _tool_summary(tool, result, request_context)
    if summary:
        result["summary"] = summary
        result["telegramText"] = _telegram_text(summary)
    return result


def _tool_summary(
    tool: dict[str, Any],
    result: dict[str, Any],
    request_context: dict[str, Any],
) -> dict[str, Any] | None:
    if str(result.get("mode", "")).endswith("inspect_only"):
        return None

    if tool.get("id") != "goplausible.weather" or not result.get("ok"):
        if tool.get("id") == "sign402.qr" and result.get("ok"):
            return _qr_tool_summary(result, request_context)
        return None

    if not result.get("txId") or result.get("amountAtomic") is None:
        return None

    city = request_context.get("city")
    resource_result = result.get("resourceResult")
    weather = _weather_for_city(resource_result if isinstance(resource_result, dict) else {}, city)
    title = f"{city} Weather" if city else "Weather"
    amount = _format_tool_amount(result.get("amountAtomic"), result.get("asset"), result)
    remaining_budget = _format_tool_amount(
        result.get("remainingBudgetAtomic"),
        result.get("asset"),
        result,
    )
    tx_id = str(result.get("txId") or "")

    summary = {
        "title": title,
        "status": str(result.get("decision", "approved_and_executed")),
        "amount": amount,
        "remainingBudget": remaining_budget,
        "txId": tx_id,
    }
    if city:
        summary["city"] = city
    if weather:
        summary.update(weather)
    return summary


def _qr_tool_summary(result: dict[str, Any], request_context: dict[str, Any]) -> dict[str, Any]:
    qr_data = str(request_context.get("qrData") or "")
    qr_image_url = _qr_image_url(qr_data)
    display_target = _qr_display_target(qr_data)
    result["qrData"] = qr_data
    result["qrImageUrl"] = qr_image_url
    result["displayTarget"] = display_target

    amount = _format_tool_amount(result.get("amountAtomic"), result.get("asset"), result)
    remaining_budget = _format_tool_amount(
        result.get("remainingBudgetAtomic"),
        result.get("asset"),
        result,
    )
    return {
        "title": "QR Code",
        "status": str(result.get("decision", "approved_and_executed")),
        "amount": amount,
        "remainingBudget": remaining_budget,
        "txId": str(result.get("txId") or ""),
        "detail": f"created for {display_target}",
        "qrData": qr_data,
        "qrImageUrl": qr_image_url,
    }


def _qr_image_url(qr_data: str) -> str:
    return "https://api.qrserver.com/v1/create-qr-code/?size=256x256&data=" + quote(
        qr_data,
        safe="",
    )


def _qr_display_target(qr_data: str) -> str:
    parsed = urlparse(qr_data)
    if parsed.netloc:
        path = parsed.path.rstrip("/")
        return parsed.netloc + path
    return qr_data[:64] + ("..." if len(qr_data) > 64 else "")


def _weather_for_city(resource_result: dict[str, Any], city: str | None) -> dict[str, str]:
    forecast = resource_result.get("forecast")
    weather: Any = None
    if city and isinstance(forecast, dict):
        city_lookup = city.lower()
        for forecast_city, forecast_value in forecast.items():
            if str(forecast_city).lower() == city_lookup:
                weather = forecast_value
                break
    if weather is None:
        weather = resource_result
    if not isinstance(weather, dict):
        return {}

    summary: dict[str, str] = {}
    if "temperature" in weather:
        temperature = str(weather["temperature"])
        summary["temperature"] = temperature if temperature.endswith("°F") else f"{temperature}°F"
    if "condition" in weather:
        summary["condition"] = str(weather["condition"])
    if "humidity" in weather:
        summary["humidity"] = str(weather["humidity"])
    if "wind" in weather:
        summary["wind"] = str(weather["wind"])
    return summary


def _format_tool_amount(amount_atomic: Any, asset: Any, result: dict[str, Any]) -> str:
    if amount_atomic is None:
        return ""
    extra: dict[str, Any] = {}
    requirement = result.get("paymentRequirements")
    if isinstance(requirement, dict) and isinstance(requirement.get("extra"), dict):
        extra = requirement["extra"]
    return _format_display_amount(
        {
            "amountAtomic": amount_atomic,
            "asset": asset,
            "extra": extra,
        }
    )


def _telegram_text(summary: dict[str, Any]) -> str:
    title = summary["title"]
    detail = str(summary.get("detail") or "")
    if detail:
        result_text = " " + detail
    else:
        weather_bits = [
            str(summary[key])
            for key in ("temperature", "condition")
            if summary.get(key)
        ]
        result_text = ": " + ", ".join(weather_bits) if weather_bits else ""
    tx_id = str(summary.get("txId", ""))
    tx_display = _transaction_display_url(tx_id)
    return (
        f"✅ {title}{result_text}. "
        f"Paid {summary.get('amount', '')}. "
        f"Tx {tx_display}. "
        f"Budget left {summary.get('remainingBudget', '')}."
    )


def _transaction_display_url(tx_id: str, *, network: str = "testnet") -> str:
    if not tx_id:
        return ""
    if tx_id.startswith(("http://", "https://")):
        return tx_id
    lora_network = "mainnet" if network == "mainnet" else "testnet"
    return f"https://lora.algokit.io/{lora_network}/transaction/{quote(tx_id, safe='')}"


def _busy_payload() -> dict[str, Any]:
    return {
        "approved": False,
        "error": "firefly_busy",
        "message": "Firefly is already handling another approval request.",
    }


def _firefly_timeout_payload(
    *,
    approved: bool | None = None,
    decision: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": "firefly_timeout",
        "message": "Firefly approval timed out. Please retry when the device is ready.",
    }
    if approved is not None:
        payload["approved"] = approved
    if decision:
        payload["decision"] = "firefly_timeout"
        payload["ok"] = False
    return payload


def _exception_payload(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision": "rejected",
        "ok": False,
        "error": str(exc),
        "errorType": type(exc).__name__,
    }
    if isinstance(exc, urllib.error.HTTPError):
        payload["httpStatus"] = exc.code
        payload["httpReason"] = exc.reason
        try:
            payload["httpBody"] = exc.read().decode("utf-8", "replace")[:1000]
        except Exception:
            pass

    if type(exc).__name__ == "AlgodHTTPError":
        args = getattr(exc, "args", ())
        if args:
            payload["algodMessage"] = str(args[0])
        code = getattr(exc, "code", None)
        if code is not None:
            payload["httpStatus"] = code
        data = getattr(exc, "data", None)
        if data is not None:
            payload["algodData"] = data
    return payload


if __name__ == "__main__":
    main()
