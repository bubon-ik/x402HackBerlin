import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sign402_gateway.server import AgentStateStore, ExternalX402Buyer, Sign402GatewayHandler


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
    def make_handler(self, path: str, body: dict | None = None, method: str = "POST"):
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
        handler = Sign402GatewayHandler(socket, ("127.0.0.1", 12345), DummyServer())
        handler.response = socket.wfile
        return handler

    def response_text(self, handler) -> str:
        return handler.response.getvalue().decode("utf-8", "replace")

    def test_approve_payment_uses_firefly(self):
        payment_hash = "b" * 64
        DummyServer.firefly.reset_mock()
        DummyServer.payment_executor.reset_mock()
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
        DummyServer.payment_executor.assert_not_called()

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
        policy_hash = "a" * 64
        approval_hash = "b" * 64
        requirement = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "amountAtomic": "50000",
            "receiver": "MERCHANT",
            "resource": "/probe?target=algorand.co",
            "paymentIntent": "intent-001",
            "purpose": "x402_api_access",
        }
        DummyServer.firefly.reset_mock()
        DummyServer.payment_executor.reset_mock()
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
        DummyServer.payment_executor.assert_called_once_with(requirement, policy_hash)

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

    def test_events_latest_can_be_written_and_read(self):
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
            post_handler = self.make_handler("/events/latest", {"event": event})
            get_handler = self.make_handler("/events/latest", method="GET")

        post_response = self.response_text(post_handler)
        get_response = self.response_text(get_handler)

        self.assertIn("HTTP/1.0 200 OK", post_response)
        self.assertIn('"ok": true', post_response)
        self.assertIn("Access-Control-Allow-Origin: *", post_response)
        self.assertIn("HTTP/1.0 200 OK", get_response)
        self.assertIn('"decision": "APPROVED & EXECUTED"', get_response)
        DummyServer.event_store.write.assert_called_once_with(event)
        DummyServer.event_store.read.assert_called_once()

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

    def test_external_x402_buyer_uses_cdp_for_base_mainnet_after_firefly_approval(self):
        policy_hash = "a" * 64
        payment_hash = "b" * 64
        policy = {
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913",
            "allowedPurpose": "x402_api_access",
            "maxPerPaymentAtomic": "10000",
            "maxBudgetAtomic": "30000",
        }
        policy_state = {
            "policy": policy,
            "policyHash": policy_hash,
            "firefly": {"approvedHash": policy_hash},
        }
        raw_payment_required = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "amount": "10000",
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913",
                    "payTo": "0x1111111111111111111111111111111111111111",
                    "extra": {
                        "name": "USD Coin",
                        "version": "2",
                        "paymentIntent": "base-intent-1",
                    },
                }
            ],
        }

        firefly = Mock()
        firefly.approve_payment_hash.return_value = {
            "approved": True,
            "approvedHash": payment_hash,
            "deviceModel": 262,
            "deviceSerial": 1056,
        }
        agent_state_store = Mock()
        agent_state_store.read_policy.return_value = policy_state
        agent_state_store.remaining_budget.return_value = 20000
        event_store = Mock()
        cdp_buyer = Mock(
            return_value={
                "status": 200,
                "body": {"ok": True},
                "paymentResponse": {"transaction": "0xTX"},
            }
        )
        algorand_builder = Mock()

        buyer = ExternalX402Buyer(
            firefly=firefly,
            payment_signature_builder=algorand_builder,
            base_payment_client=cdp_buyer,
            event_store=event_store,
            agent_state_store=agent_state_store,
        )

        with (
            patch(
                "sign402_gateway.server.fetch_x402_payment_required",
                return_value=raw_payment_required,
            ),
            patch(
                "sign402_gateway.server.build_payment_commitment",
                return_value={"paymentHash": payment_hash, "commitment": {"type": "sign402-payment"}},
            ),
        ):
            result = buyer("https://api.example.com/paid-report")

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "official_x402_base_cdp")
        self.assertEqual(result["txId"], "0xTX")
        firefly.approve_payment_hash.assert_called_once()
        self.assertEqual(
            firefly.approve_payment_hash.call_args.kwargs["context_lines"],
            ["x402 PAYMENT", "0.01 USDC", "x402 API"],
        )
        cdp_buyer.assert_called_once_with("https://api.example.com/paid-report")
        algorand_builder.assert_not_called()
        agent_state_store.record_payment.assert_called_once_with(
            policy_hash,
            "base-intent-1",
            10000,
        )

    def test_agent_tools_lists_paid_tool_catalog(self):
        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/tools", method="GET")

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"mode": "paid_tool_catalog"', response)
        self.assertIn('"id": "goplausible.weather"', response)
        self.assertIn('"mcpStyleName": "get_weather"', response)
        self.assertIn('"id": "base.sign402.report"', response)
        self.assertIn('"mcpStyleName": "get_sign402_report"', response)

    def test_agent_inspect_base_tool_resolves_alias_and_returns_offer(self):
        policy_hash = "c" * 64
        DummyServer.x402_inspector.reset_mock()
        DummyServer.x402_inspector.return_value = {
            "ok": True,
            "mode": "inspect_only",
            "resourceUrl": "http://127.0.0.1:4021/paid/sign402-report",
            "paymentRequirements": {
                "network": "base-mainnet",
                "amountAtomic": "10000",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            },
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler(
                "/agent/inspect-tool",
                {"tool": "sign402-report", "policyHash": policy_hash},
            )

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"toolId": "base.sign402.report"', response)
        self.assertIn('"command": "buy base sign402 report"', response)
        DummyServer.x402_inspector.assert_called_once_with(
            "http://127.0.0.1:4021/paid/sign402-report",
            policy_hash,
        )

    def test_agent_buy_base_tool_uses_x402_buyer_and_writes_tool_event(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.x402_buyer.return_value = {
            "decision": "approved_and_executed",
            "ok": True,
            "mode": "official_x402_base_cdp",
            "resourceUrl": "http://127.0.0.1:4021/paid/sign402-report",
            "txId": "0xTX",
            "amountAtomic": "10000",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "network": "base-mainnet",
            "remainingBudgetAtomic": "80000",
            "paymentRequirements": {
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                "amountAtomic": "10000",
                "extra": {
                    "name": "USD Coin",
                    "version": "2",
                },
            },
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/buy-tool", {"tool": "base-report"})

        response = self.response_text(handler)
        body = json.loads(response.split("\r\n\r\n", 1)[1])

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"decision": "approved_and_executed"', response)
        self.assertIn('"toolName": "Base Sign402 Report"', response)
        self.assertEqual(
            body["telegramText"],
            "✅ Base Sign402 Report unlocked. Paid 0.01 USDC. Tx https://basescan.org/tx/0xTX. Budget left 0.08 USDC.",
        )
        DummyServer.x402_buyer.assert_called_once_with(
            "http://127.0.0.1:4021/paid/sign402-report"
        )
        DummyServer.event_store.write.assert_called_once()
        saved_event = DummyServer.event_store.write.call_args.args[0]
        self.assertEqual(saved_event["toolId"], "base.sign402.report")
        self.assertEqual(saved_event["command"], "buy base sign402 report")
        self.assertEqual(saved_event["telegramText"], body["telegramText"])

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

    def test_agent_buy_tool_uses_x402_buyer_and_writes_tool_event(self):
        DummyServer.x402_buyer.reset_mock()
        DummyServer.event_store.reset_mock()
        DummyServer.x402_buyer.return_value = {
            "decision": "approved_and_executed",
            "ok": True,
            "resourceUrl": "https://x402.goplausible.xyz/examples/weather",
            "txId": "TXID",
        }

        with patch("sys.stderr", io.StringIO()):
            handler = self.make_handler("/agent/buy-tool", {"tool": "get_weather"})

        response = self.response_text(handler)

        self.assertIn("HTTP/1.0 200 OK", response)
        self.assertIn('"decision": "approved_and_executed"', response)
        self.assertIn('"toolName": "GoPlausible Weather"', response)
        DummyServer.x402_buyer.assert_called_once_with(
            "https://x402.goplausible.xyz/examples/weather"
        )
        DummyServer.event_store.write.assert_called_once()
        saved_event = DummyServer.event_store.write.call_args.args[0]
        self.assertEqual(saved_event["toolId"], "goplausible.weather")
        self.assertEqual(saved_event["command"], "buy goplausible weather")

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


if __name__ == "__main__":
    unittest.main()
