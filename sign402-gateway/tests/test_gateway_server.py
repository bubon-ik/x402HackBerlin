import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sign402_gateway.server import AgentStateStore, Sign402GatewayHandler


class DummyServer:
    firefly = Mock()
    payment_executor = Mock()
    firefly_busy = False
    event_store = Mock()
    agent_state_store = Mock()
    agent_buy_probe = Mock()
    x402_inspector = Mock()
    x402_buyer = Mock()


class FakeSocket:
    def __init__(self, request: bytes):
        self.rfile = io.BytesIO(request)
        self.wfile = io.BytesIO()

    def makefile(self, mode, buffering=None):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, data):
        self.wfile.write(data)


class GatewayServerTests(unittest.TestCase):
    def setUp(self):
        DummyServer.firefly_busy = False
        for mock in (
            DummyServer.firefly,
            DummyServer.payment_executor,
            DummyServer.event_store,
            DummyServer.agent_state_store,
            DummyServer.agent_buy_probe,
            DummyServer.x402_inspector,
            DummyServer.x402_buyer,
        ):
            mock.reset_mock(return_value=True, side_effect=True)

    def make_handler(
        self,
        path: str,
        body: dict | None = None,
        method: str = "POST",
        server=None,
    ):
        encoded = b""
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")

        request = (
            f"{method} {path} HTTP/1.1\r\n".encode("ascii")
            + f"Content-Length: {len(encoded)}\r\n".encode("ascii")
            + b"Content-Type: application/json\r\n"
            + b"\r\n"
            + encoded
        )
        socket = FakeSocket(request)
        handler = Sign402GatewayHandler(socket, ("127.0.0.1", 12345), server or DummyServer())
        handler.response = socket.wfile
        return handler

    def response_text(self, handler) -> str:
        return handler.response.getvalue().decode("utf-8", "replace")

    def response_json(self, handler) -> dict:
        response = self.response_text(handler)
        _, body = response.split("\r\n\r\n", 1)
        return json.loads(body)

    def test_agent_manifest_exposes_paid_tool_discovery_metadata(self):
        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/manifest", method="GET")

        response = self.response_text(handler)
        body = self.response_json(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertEqual(body["name"], "Hermes Sign402 Gateway")
        self.assertEqual(body["x402Version"], 2)
        self.assertEqual(body["network"], "algorand-testnet")
        self.assertEqual(body["tools"][0]["id"], "goplausible.weather")
        self.assertEqual(body["tools"][0]["price"], "0.01 USDC")
        self.assertEqual(body["tools"][0]["asset"], "10458941")
        self.assertTrue(body["tools"][0]["requiresFireflyApproval"])
        self.assertEqual(body["tools"][0]["buyEndpoint"], "/agent/buy-tool")
        self.assertIn("city", body["tools"][0]["inputSchema"]["properties"])
        qr_tool = next(tool for tool in body["tools"] if tool["id"] == "sign402.qr")
        self.assertEqual(qr_tool["mcpStyleName"], "create_qr_code")
        self.assertIn("url", qr_tool["inputSchema"]["properties"])
        self.assertEqual(qr_tool["paymentResourceUrl"], "https://x402.goplausible.xyz/examples/weather")
        self.assertFalse(body["security"]["agentPrivateKeyAccess"])
        self.assertEqual(body["security"]["paymentApproval"], "Firefly required")

    def test_well_known_x402_manifest_matches_agent_manifest(self):
        with patch("sys.stderr", io.StringIO()):
            well_known = self.make_handler("/.well-known/x402.json", method="GET")
            manifest = self.make_handler("/agent/manifest", method="GET")

        self.assertEqual(self.response_json(well_known), self.response_json(manifest))

    def test_approve_payment_uses_firefly(self):
        payment_hash = "b" * 64
        DummyServer.firefly.reset_mock()
        DummyServer.payment_executor.reset_mock()
        DummyServer.agent_state_store.reset_mock()
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
                "/approve-payment",
                {"paymentHash": payment_hash, "paymentCommitment": {"type": "sign402-payment"}},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"approved": true', response)
        DummyServer.firefly.approve_payment_hash.assert_called_once_with(
            payment_hash,
            context_lines=["x402 PAYMENT", "sign402 approval"],
        )
        DummyServer.agent_state_store.record_payment_approval.assert_called_once_with(
            payment_hash,
            DummyServer.firefly.approve_payment_hash.return_value,
        )
        DummyServer.payment_executor.assert_not_called()

    def test_approve_payment_firefly_timeout_returns_gateway_timeout(self):
        payment_hash = "b" * 64
        DummyServer.firefly.reset_mock()
        DummyServer.agent_state_store.reset_mock()
        DummyServer.firefly_busy = False
        DummyServer.firefly.approve_payment_hash.side_effect = TimeoutError(
            "Firefly payment approval timed out after 90 seconds."
        )

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/approve-payment", {"paymentHash": payment_hash})

        response = self.response_text(handler)
        body = self.response_json(handler)

        self.assertIn("HTTP/1.0 504 Gateway Timeout", response)
        self.assertFalse(body["approved"])
        self.assertEqual(body["error"], "firefly_timeout")
        self.assertIn("Please retry", body["message"])
        DummyServer.agent_state_store.record_payment_approval.assert_not_called()

    def test_approve_policy_stores_policy_for_agent_endpoint(self):
        policy = {
            "version": "1",
            "agentId": "hermes-demo",
            "policyId": "policy-test",
            "allowedPurpose": "x402_api_access",
            "asset": "ALGO_TEST",
            "maxBudgetAtomic": "1000000",
            "maxPerPaymentAtomic": "50000",
            "nonce": "test",
        }
        DummyServer.firefly.reset_mock()
        DummyServer.agent_state_store.reset_mock()
        DummyServer.firefly_busy = False

        from sign402_bridge.policy import hash_policy

        policy_hash = hash_policy(policy)
        DummyServer.firefly.approve_payment_hash.return_value = {
            "approved": True,
            "approvedHash": policy_hash,
            "deviceModel": 262,
            "deviceSerial": 1056,
            "raw": "<OK",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/approve-policy", {"policy": policy})

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"approved": true', response)
        DummyServer.firefly.approve_payment_hash.assert_called_once_with(policy_hash)
        DummyServer.firefly.approve_policy_hash.assert_not_called()
        DummyServer.agent_state_store.write_policy.assert_called_once()
        stored = DummyServer.agent_state_store.write_policy.call_args.args[0]
        self.assertEqual(stored["policy"], policy)
        self.assertEqual(stored["policyHash"], policy_hash)
        self.assertEqual(stored["firefly"]["approvedHash"], policy_hash)

    def test_execute_payment_uses_local_executor_without_exposing_secrets(self):
        from sign402_live.flow import build_payment_commitment

        policy_hash = "a" * 64
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "amountAtomic": "50000",
            "receiver": "MERCHANT",
            "resource": "/probe?target=algorand.co",
            "paymentIntent": "intent-001",
            "purpose": "x402_api_access",
        }
        approval_hash = build_payment_commitment(requirement, policy_hash)["paymentHash"]
        policy = {
            "asset": "ALGO_TEST",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "50000",
        }
        DummyServer.firefly.reset_mock()
        DummyServer.payment_executor.reset_mock()
        DummyServer.agent_state_store.reset_mock()
        DummyServer.agent_state_store.read_policy.return_value = {
            "policy": policy,
            "policyHash": policy_hash,
            "firefly": {"approvedHash": policy_hash},
        }
        DummyServer.agent_state_store.consume_payment_approval.return_value = True
        DummyServer.agent_state_store.remaining_budget.return_value = 50000
        DummyServer.payment_executor.return_value = {
            "txId": "TXID",
            "network": "algorand-testnet",
            "receiver": "MERCHANT",
            "amountAtomic": "50000",
            "asset": "ALGO_TEST",
            "paymentIntent": "intent-001",
            "policyHash": policy_hash,
            "note": f"sign402:{policy_hash}:intent-001",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/execute-payment",
                {
                    "policyHash": policy_hash,
                    "paymentApprovalHash": approval_hash,
                    "paymentRequirements": requirement,
                },
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"ok": true', response)
        self.assertIn('"txId": "TXID"', response)
        self.assertNotIn("private", response.lower())
        self.assertNotIn("mnemonic", response.lower())
        DummyServer.agent_state_store.validate_policy_allows.assert_called_once_with(
            policy,
            policy_hash,
            requirement,
        )
        DummyServer.agent_state_store.consume_payment_approval.assert_called_once_with(
            approval_hash
        )
        DummyServer.agent_state_store.record_payment.assert_called_once_with(
            policy_hash,
            "intent-001",
            50000,
        )
        DummyServer.payment_executor.assert_called_once_with(requirement, policy_hash)

    def test_execute_payment_rejects_hash_not_bound_to_requirements(self):
        policy_hash = "a" * 64
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "amountAtomic": "50000",
            "receiver": "MERCHANT",
            "resource": "/probe?target=algorand.co",
            "paymentIntent": "intent-001",
            "purpose": "x402_api_access",
        }
        DummyServer.payment_executor.reset_mock()
        DummyServer.agent_state_store.reset_mock()

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/execute-payment",
                {
                    "policyHash": policy_hash,
                    "paymentApprovalHash": "b" * 64,
                    "paymentRequirements": requirement,
                },
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        self.assertIn("does not match payment commitment", response)
        DummyServer.agent_state_store.consume_payment_approval.assert_not_called()
        DummyServer.payment_executor.assert_not_called()

    def test_execute_payment_rejects_missing_or_consumed_firefly_approval(self):
        from sign402_live.flow import build_payment_commitment

        policy_hash = "a" * 64
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "amountAtomic": "50000",
            "receiver": "MERCHANT",
            "resource": "/probe?target=algorand.co",
            "paymentIntent": "intent-001",
            "purpose": "x402_api_access",
        }
        approval_hash = build_payment_commitment(requirement, policy_hash)["paymentHash"]
        policy = {
            "asset": "ALGO_TEST",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "50000",
        }
        DummyServer.payment_executor.reset_mock()
        DummyServer.agent_state_store.reset_mock()
        DummyServer.agent_state_store.read_policy.return_value = {
            "policy": policy,
            "policyHash": policy_hash,
            "firefly": {"approvedHash": policy_hash},
        }
        DummyServer.agent_state_store.consume_payment_approval.return_value = False

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/execute-payment",
                {
                    "policyHash": policy_hash,
                    "paymentApprovalHash": approval_hash,
                    "paymentRequirements": requirement,
                },
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        self.assertIn("No unused Firefly approval", response)
        DummyServer.payment_executor.assert_not_called()

    def test_execute_payment_rejects_invalid_hash_before_executor(self):
        DummyServer.payment_executor.reset_mock()
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "amountAtomic": "50000",
            "receiver": "MERCHANT",
            "paymentIntent": "intent-001",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/execute-payment",
                {
                    "policyHash": "not-a-hash",
                    "paymentApprovalHash": "b" * 64,
                    "paymentRequirements": requirement,
                },
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        DummyServer.payment_executor.assert_not_called()

    def test_events_latest_can_be_read(self):
        event = {
            "decision": "APPROVED & EXECUTED",
            "policyHash": "a" * 64,
            "paymentApprovalHash": "b" * 64,
            "txId": "TXID",
        }
        DummyServer.event_store.reset_mock()
        DummyServer.event_store.write.return_value = event
        DummyServer.event_store.read.return_value = event

        with patch("sys.stderr", io.StringIO()):
            get_handler = self.make_handler("/events/latest", method="GET")

        get_response = self.response_text(get_handler)

        self.assertIn("HTTP/1.0 200 OK", get_response)
        self.assertIn('"decision": "APPROVED & EXECUTED"', get_response)
        DummyServer.event_store.write.assert_not_called()
        DummyServer.event_store.read.assert_called_once()

    def test_events_latest_rejects_external_writes(self):
        DummyServer.event_store.reset_mock()

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/events/latest",
                {"event": {"decision": "FAKE_SUCCESS", "txId": "FAKE"}},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 404 Not Found", response)
        DummyServer.event_store.write.assert_not_called()

    def test_agent_buy_probe_runs_single_orchestrated_flow(self):
        DummyServer.agent_buy_probe.reset_mock()
        DummyServer.agent_buy_probe.return_value = {
            "decision": "approved_and_executed",
            "target": "algorand.co",
            "txId": "TXID",
            "result": "reachable",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/buy-probe", {"target": "algorand.co"})

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"decision": "approved_and_executed"', response)
        DummyServer.agent_buy_probe.assert_called_once_with("algorand.co")

    def test_agent_inspect_x402_returns_normalized_external_requirements(self):
        policy_hash = "c" * 64
        DummyServer.x402_inspector.reset_mock()
        DummyServer.x402_inspector.return_value = {
            "ok": True,
            "resourceUrl": "https://example.x402.goplausible.xyz/protected",
            "paymentRequirements": {
                "network": "algorand-testnet",
                "x402Network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
                "asset": "10458941",
                "amountAtomic": "10000",
                "receiver": "PAYEE",
                "resource": "https://example.x402.goplausible.xyz/protected",
                "paymentIntent": "intent-from-resource",
                "purpose": "x402_api_access",
            },
            "paymentCommitment": {
                "paymentHash": "d" * 64,
                "commitment": {"type": "sign402-payment"},
            },
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/inspect-x402",
                {
                    "url": "https://example.x402.goplausible.xyz/protected",
                    "policyHash": policy_hash,
                },
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"ok": true', response)
        self.assertIn('"amountAtomic": "10000"', response)
        DummyServer.x402_inspector.assert_called_once_with(
            "https://example.x402.goplausible.xyz/protected",
            policy_hash,
        )

    def test_agent_buy_x402_runs_official_x402_buyer(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.x402_buyer.return_value = {
            "decision": "approved_and_executed",
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "txId": "TXID",
            "result": "paid_resource_access_granted",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/buy-x402",
                {"url": "https://x402.goplausible.xyz/examples/weather"},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"decision": "approved_and_executed"', response)
        DummyServer.x402_buyer.assert_called_once_with(
            "https://x402.goplausible.xyz/examples/weather"
        )

    def test_agent_tools_lists_paid_tool_catalog(self):
        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/tools", method="GET")

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"mode": "paid_tool_catalog"', response)
        self.assertIn('"id": "goplausible.weather"', response)
        self.assertIn('"mcpStyleName": "get_weather"', response)

    def test_agent_inspect_tool_resolves_alias_and_returns_offer(self):
        policy_hash = "c" * 64
        DummyServer.x402_inspector.reset_mock()
        DummyServer.x402_inspector.return_value = {
            "ok": True,
            "mode": "inspect_only",
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "paymentRequirements": {"amountAtomic": "10000", "asset": "10458941"},
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/inspect-tool",
                {"tool": "weather", "policyHash": policy_hash},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"toolId": "goplausible.weather"', response)
        self.assertIn('"command": "buy goplausible weather"', response)
        DummyServer.x402_inspector.assert_called_once_with(
            "https://x402.goplausible.xyz/examples/weather",
            policy_hash,
        )

    def test_agent_inspect_x402_rejects_local_or_non_https_urls(self):
        DummyServer.x402_inspector.reset_mock()

        for resource_url in (
            "file:///etc/passwd",
            "http://127.0.0.1:8090/probe",
            "https://localhost/internal",
            "https://192.168.1.10/protected",
        ):
            with self.subTest(resource_url=resource_url), patch(
                "sys.stderr",
                io.StringIO(),
            ):
                handler = self.make_handler(
                    "/agent/inspect-x402",
                    {"url": resource_url, "policyHash": "a" * 64},
                )

            response = self.response_text(handler)
            self.assertIn("HTTP/1.0 400 Bad Request", response)

        DummyServer.x402_inspector.assert_not_called()

    def test_agent_buy_tool_uses_x402_buyer_and_writes_tool_event(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.x402_buyer.return_value = {
            "decision": "approved_and_executed",
            "ok": True,
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "txId": "TXID",
            "amountAtomic": "10000",
            "asset": "10458941",
            "remainingBudgetAtomic": "990000",
            "resourceResult": {
                "temperature": "55°F",
                "condition": "Clear",
            },
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/buy-tool",
                {"tool": "get_weather", "city": "Tokyo"},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"decision": "approved_and_executed"', response)
        self.assertIn('"toolName": "GoPlausible Weather"', response)
        self.assertIn('"city": "Tokyo"', response)
        self.assertIn('"title": "Tokyo Weather"', response)
        self.assertIn('"telegramText": "✅ Tokyo Weather: 55°F, Clear. Paid 0.01 USDC. Tx https://lora.algokit.io/testnet/transaction/TXID. Budget left 0.99 USDC."', response)
        DummyServer.x402_buyer.assert_called_once_with(
            "https://x402.goplausible.xyz/examples/weather"
        )
        DummyServer.event_store.write.assert_called_once()
        saved_event = DummyServer.event_store.write.call_args.args[0]
        self.assertEqual(saved_event["toolId"], "goplausible.weather")
        self.assertEqual(saved_event["command"], "buy goplausible weather")
        self.assertEqual(saved_event["city"], "Tokyo")
        self.assertEqual(saved_event["summary"]["title"], "Tokyo Weather")

    def test_agent_buy_tool_summary_allows_missing_city(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.x402_buyer.return_value = {
            "decision": "approved_and_executed",
            "ok": True,
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "txId": "TXID",
            "amountAtomic": "10000",
            "asset": "10458941",
            "remainingBudgetAtomic": "990000",
            "resourceResult": {
                "temperature": "55°F",
                "condition": "Clear",
            },
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/buy-tool", {"tool": "get_weather"})

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"title": "Weather"', response)
        self.assertIn('"telegramText": "✅ Weather: 55°F, Clear. Paid 0.01 USDC. Tx https://lora.algokit.io/testnet/transaction/TXID. Budget left 0.99 USDC."', response)

    def test_agent_buy_qr_tool_generates_qr_receipt_after_x402_payment(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.x402_buyer.return_value = {
            "decision": "approved_and_executed",
            "ok": True,
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "txId": "TXID",
            "amountAtomic": "10000",
            "asset": "10458941",
            "remainingBudgetAtomic": "990000",
            "resourceResult": {
                "temperature": "55°F",
                "condition": "Clear",
            },
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/buy-tool",
                {"tool": "qr", "url": "https://github.com/bubon-ik/x402HackBerlin"},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"toolName": "Sign402 QR Code"', response)
        self.assertIn('"qrData": "https://github.com/bubon-ik/x402HackBerlin"', response)
        self.assertIn('"qrImageUrl": "https://api.qrserver.com/v1/create-qr-code/?size=256x256&data=https%3A%2F%2Fgithub.com%2Fbubon-ik%2Fx402HackBerlin"', response)
        self.assertIn('"telegramText": "✅ QR Code created for github.com/bubon-ik/x402HackBerlin. Paid 0.01 USDC. Tx https://lora.algokit.io/testnet/transaction/TXID. Budget left 0.99 USDC."', response)
        DummyServer.x402_buyer.assert_called_once_with(
            "https://x402.goplausible.xyz/examples/weather",
            firefly_context={
                "title": "x402 QR CODE",
                "service": "Sign402 Generator",
            },
        )
        DummyServer.event_store.write.assert_called_once()
        saved_event = DummyServer.event_store.write.call_args.args[0]
        self.assertEqual(saved_event["toolId"], "sign402.qr")
        self.assertEqual(saved_event["qrData"], "https://github.com/bubon-ik/x402HackBerlin")
        self.assertIn("qrImageUrl", saved_event)

    def test_agent_buy_tool_firefly_timeout_returns_gateway_timeout(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.firefly_busy = False
        DummyServer.x402_buyer.side_effect = TimeoutError(
            "Firefly payment approval timed out after 90 seconds."
        )

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/buy-tool",
                {"tool": "goplausible.weather", "city": "Berlin"},
            )

        response = self.response_text(handler)
        body = self.response_json(handler)

        self.assertIn("HTTP/1.0 504 Gateway Timeout", response)
        self.assertFalse(body["ok"])
        self.assertEqual(body["decision"], "firefly_timeout")
        self.assertEqual(body["error"], "firefly_timeout")
        self.assertIn("Please retry", body["message"])
        DummyServer.event_store.write.assert_not_called()

    def test_agent_buy_tool_does_not_reprompt_firefly_after_cancel_retry(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.firefly_busy = False
        DummyServer.x402_buyer.return_value = {
            "decision": "rejected_by_firefly",
            "ok": False,
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "paymentApprovalHash": "a" * 64,
            "firefly": {
                "approved": False,
                "approvedHash": "a" * 64,
                "error": "PAYMENT rejected by user",
            },
        }

        payload = {"tool": "goplausible.weather", "city": "Berlin"}
        server = DummyServer()
        with patch("sys.stderr", io.StringIO()):
            first = self.make_handler("/agent/buy-tool", payload, server=server)
            second = self.make_handler("/agent/buy-tool", payload, server=server)

        first_body = self.response_json(first)
        second_body = self.response_json(second)

        self.assertFalse(first_body["ok"])
        self.assertEqual(first_body["decision"], "rejected_by_firefly")
        self.assertEqual(
            first_body["telegramText"],
            "❌ Purchase canceled on Firefly. No payment was made.",
        )
        self.assertFalse(second_body["ok"])
        self.assertEqual(second_body["decision"], "rejected_by_firefly")
        self.assertEqual(
            second_body["telegramText"],
            "❌ Purchase canceled on Firefly. No payment was made.",
        )
        self.assertTrue(second_body["duplicateSuppressed"])
        self.assertIn("not retried", second_body["message"])
        DummyServer.x402_buyer.assert_called_once_with(
            "https://x402.goplausible.xyz/examples/weather"
        )

    def test_agent_buy_qr_tool_requires_data_before_payment(self):
        DummyServer.x402_buyer.reset_mock()

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/buy-tool", {"tool": "qr"})

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        self.assertIn("qr tool requires url, text, data, or target", response)
        DummyServer.x402_buyer.assert_not_called()

    def test_agent_buy_qr_tool_rejects_oversized_payload_before_payment(self):
        DummyServer.x402_buyer.reset_mock()

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/buy-tool",
                {"tool": "qr", "text": "x" * 2049},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        self.assertIn("qr payload must be at most 2048 characters", response)
        DummyServer.x402_buyer.assert_not_called()

    def test_gateway_rejects_oversized_json_body(self):
        DummyServer.x402_buyer.reset_mock()

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/buy-tool",
                {"tool": "qr", "text": "x" * 70000},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 400 Bad Request", response)
        self.assertIn("request body is too large", response)
        DummyServer.x402_buyer.assert_not_called()

    def test_external_x402_buyer_sends_human_payment_context_to_firefly(self):
        from sign402_gateway.server import ExternalX402Buyer

        policy_hash = "a" * 64
        policy = {
            "asset": "10458941",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "10000",
        }
        requirement = {
            "network": "algorand-testnet",
            "x402Network": "algorand:testnet",
            "asset": "10458941",
            "amountAtomic": "10000",
            "receiver": "PAYEE",
            "resource": "https://x402.goplausible.xyz/examples/weather",
            "paymentIntent": "intent-001",
            "purpose": "x402_api_access",
            "extra": {"name": "USDC", "decimals": 6},
        }

        firefly = Mock()
        event_store = Mock()
        agent_state_store = Mock()
        agent_state_store.read_policy.return_value = {
            "policy": policy,
            "policyHash": policy_hash,
            "firefly": {"approvedHash": policy_hash},
        }
        agent_state_store.remaining_budget.return_value = 90000
        payment_signature_builder = Mock(return_value={"headerValue": "PAYMENT-SIGNATURE token"})

        def approve_payment_hash(payment_hash, context_lines=None):
            return {
                "approved": True,
                "approvedHash": payment_hash,
                "deviceModel": 262,
                "deviceSerial": 1056,
            }

        firefly.approve_payment_hash.side_effect = approve_payment_hash

        buyer = ExternalX402Buyer(
            firefly=firefly,
            payment_signature_builder=payment_signature_builder,
            event_store=event_store,
            agent_state_store=agent_state_store,
        )

        with (
            patch("sign402_gateway.server.fetch_x402_payment_required", return_value={"accepts": []}),
            patch("sign402_gateway.server.normalize_x402_payment_required", return_value=requirement),
            patch(
                "sign402_gateway.server.fetch_x402_paid_resource",
                return_value={
                    "status": 200,
                    "paymentResponse": {"transaction": "TXID"},
                },
            ),
        ):
            result = buyer("https://x402.goplausible.xyz/examples/weather")

        self.assertEqual(result["decision"], "approved_and_executed")
        firefly.approve_payment_hash.assert_called_once()
        self.assertEqual(
            firefly.approve_payment_hash.call_args.kwargs["context_lines"],
            ["x402 WEATHER", "0.01 USDC", "GoPlausible API"],
        )

    def test_external_x402_buyer_uses_explicit_tool_context_for_firefly(self):
        from sign402_gateway.server import ExternalX402Buyer

        policy_hash = "a" * 64
        policy = {
            "asset": "10458941",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "10000",
        }
        requirement = {
            "network": "algorand-testnet",
            "x402Network": "algorand:testnet",
            "asset": "10458941",
            "amountAtomic": "10000",
            "receiver": "PAYEE",
            "resource": "https://x402.goplausible.xyz/examples/weather",
            "paymentIntent": "intent-qr-001",
            "purpose": "x402_api_access",
            "extra": {"name": "USDC", "decimals": 6},
        }

        firefly = Mock()
        event_store = Mock()
        agent_state_store = Mock()
        agent_state_store.read_policy.return_value = {
            "policy": policy,
            "policyHash": policy_hash,
            "firefly": {"approvedHash": policy_hash},
        }
        agent_state_store.remaining_budget.return_value = 90000
        payment_signature_builder = Mock(return_value={"headerValue": "PAYMENT-SIGNATURE token"})

        def approve_payment_hash(payment_hash, context_lines=None):
            return {
                "approved": True,
                "approvedHash": payment_hash,
                "deviceModel": 262,
                "deviceSerial": 1056,
            }

        firefly.approve_payment_hash.side_effect = approve_payment_hash
        buyer = ExternalX402Buyer(
            firefly=firefly,
            payment_signature_builder=payment_signature_builder,
            event_store=event_store,
            agent_state_store=agent_state_store,
        )

        with (
            patch("sign402_gateway.server.fetch_x402_payment_required", return_value={"accepts": []}),
            patch("sign402_gateway.server.normalize_x402_payment_required", return_value=requirement),
            patch(
                "sign402_gateway.server.fetch_x402_paid_resource",
                return_value={
                    "status": 200,
                    "paymentResponse": {"transaction": "TXID"},
                },
            ),
        ):
            buyer(
                "https://x402.goplausible.xyz/examples/weather",
                firefly_context={
                    "title": "x402 QR CODE",
                    "service": "Sign402 Generator",
                },
            )

        self.assertEqual(
            firefly.approve_payment_hash.call_args.kwargs["context_lines"],
            ["x402 QR CODE", "0.01 USDC", "Sign402 Generator"],
        )


class AgentStateStoreTests(unittest.TestCase):
    def make_store(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return AgentStateStore(Path(temp_dir.name) / "agent-state.json")

    def test_validate_policy_allows_matching_payment_and_tracks_budget(self):
        store = self.make_store()
        policy = {
            "asset": "ALGO_TEST",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "50000",
        }
        policy_hash = "a" * 64
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "purpose": "x402_api_access",
            "amountAtomic": "50000",
            "paymentIntent": "intent-001",
        }
        store.write_policy(
            {
                "policy": policy,
                "policyHash": policy_hash,
                "firefly": {"approvedHash": policy_hash},
            }
        )

        store.validate_policy_allows(policy, policy_hash, requirement)
        store.record_payment(policy_hash, "intent-001", 50000)

        self.assertEqual(store.remaining_budget(policy_hash), 50000)

    def test_validate_policy_rejects_replayed_intent(self):
        store = self.make_store()
        policy = {
            "asset": "ALGO_TEST",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "50000",
        }
        policy_hash = "a" * 64
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "purpose": "x402_api_access",
            "amountAtomic": "50000",
            "paymentIntent": "intent-001",
        }
        store.write_policy(
            {
                "policy": policy,
                "policyHash": policy_hash,
                "firefly": {"approvedHash": policy_hash},
            }
        )
        store.record_payment(policy_hash, "intent-001", 50000)

        with self.assertRaisesRegex(ValueError, "paymentIntent already used"):
            store.validate_policy_allows(policy, policy_hash, requirement)

    def test_validate_policy_rejects_non_testnet_payment(self):
        store = self.make_store()
        policy = {
            "asset": "10458941",
            "allowedPurpose": "x402_api_access",
            "maxBudgetAtomic": "100000",
            "maxPerPaymentAtomic": "50000",
        }
        policy_hash = "a" * 64
        requirement = {
            "network": "algorand-mainnet",
            "asset": "10458941",
            "purpose": "x402_api_access",
            "amountAtomic": "10000",
            "paymentIntent": "intent-mainnet",
        }
        store.write_policy(
            {
                "policy": policy,
                "policyHash": policy_hash,
                "firefly": {"approvedHash": policy_hash},
            }
        )

        with self.assertRaisesRegex(ValueError, "Only algorand-testnet"):
            store.validate_policy_allows(policy, policy_hash, requirement)

    def test_payment_approval_can_only_be_consumed_once(self):
        store = self.make_store()
        policy_hash = "a" * 64
        payment_hash = "b" * 64
        store.write_policy(
            {
                "policy": {
                    "asset": "ALGO_TEST",
                    "allowedPurpose": "x402_api_access",
                    "maxBudgetAtomic": "100000",
                    "maxPerPaymentAtomic": "50000",
                },
                "policyHash": policy_hash,
                "firefly": {"approvedHash": policy_hash},
            }
        )
        store.record_payment_approval(
            payment_hash,
            {
                "approved": True,
                "approvedHash": payment_hash,
                "deviceModel": 262,
                "deviceSerial": 1056,
            },
        )

        self.assertTrue(store.consume_payment_approval(payment_hash))
        self.assertFalse(store.consume_payment_approval(payment_hash))


if __name__ == "__main__":
    unittest.main()
