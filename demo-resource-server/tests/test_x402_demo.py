import base64
import json
import unittest
from unittest.mock import patch

from x402_demo.core import (
    PAYMENT_PRICE,
    build_payment_required,
    encode_payment_proof,
    parse_payment_proof,
    verify_payment_proof,
)


class X402DemoTests(unittest.TestCase):
    def test_build_payment_required_for_probe(self):
        requirement = build_payment_required("algorand.co")

        self.assertEqual(requirement["status"], 402)
        self.assertEqual(requirement["x402Version"], "demo-1")
        self.assertEqual(requirement["paymentRequirements"]["amountAtomic"], PAYMENT_PRICE)
        self.assertEqual(requirement["paymentRequirements"]["network"], "algorand-testnet")
        self.assertEqual(requirement["paymentRequirements"]["resource"], "/probe?target=algorand.co")

    def test_build_payment_required_generates_fresh_payment_intent(self):
        first = build_payment_required("algorand.co")["paymentRequirements"]
        second = build_payment_required("algorand.co")["paymentRequirements"]

        self.assertNotEqual(first["paymentIntent"], second["paymentIntent"])

    def test_payment_proof_round_trip(self):
        proof = {"txId": "TEST_TX", "paymentIntent": "probe-algorand-co-001"}

        encoded = encode_payment_proof(proof)

        self.assertEqual(parse_payment_proof(encoded), proof)

    def test_parse_payment_proof_rejects_invalid_base64(self):
        with self.assertRaises(ValueError):
            parse_payment_proof("not valid base64")

    def test_verify_payment_proof_rejects_matching_but_unverified_payload(self):
        requirement = build_payment_required("algorand.co")["paymentRequirements"]
        proof = {
            "txId": "TEST_TX",
            "network": "algorand-testnet",
            "receiver": requirement["receiver"],
            "amountAtomic": requirement["amountAtomic"],
            "asset": requirement["asset"],
            "resource": requirement["resource"],
            "paymentIntent": requirement["paymentIntent"],
            "policyHash": "a" * 64,
        }

        result = verify_payment_proof(proof, requirement, used_intents=set())

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "verificationMode must be algorand")

    def test_verify_payment_proof_uses_algorand_verifier(self):
        requirement = build_payment_required("algorand.co")["paymentRequirements"]
        proof = {
            "verificationMode": "algorand",
            "txId": "TEST_TX",
            "network": "algorand-testnet",
            "receiver": requirement["receiver"],
            "amountAtomic": requirement["amountAtomic"],
            "asset": requirement["asset"],
            "resource": requirement["resource"],
            "paymentIntent": requirement["paymentIntent"],
            "policyHash": "a" * 64,
        }

        with patch(
            "x402_demo.core.verify_algorand_payment_proof",
            return_value={"ok": True, "confirmedRound": 123},
        ) as verifier:
            result = verify_payment_proof(proof, requirement, used_intents=set())

        self.assertTrue(result["ok"])
        verifier.assert_called_once_with(proof, requirement)

    def test_verify_payment_proof_rejects_replay(self):
        requirement = build_payment_required("algorand.co")["paymentRequirements"]
        proof = {
            "txId": "TEST_TX",
            "network": "algorand-testnet",
            "receiver": requirement["receiver"],
            "amountAtomic": requirement["amountAtomic"],
            "asset": requirement["asset"],
            "resource": requirement["resource"],
            "paymentIntent": requirement["paymentIntent"],
            "policyHash": "a" * 64,
        }

        result = verify_payment_proof(
            proof,
            requirement,
            used_intents={requirement["paymentIntent"]},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "paymentIntent already used")

    def test_verify_payment_proof_rejects_wrong_amount(self):
        requirement = build_payment_required("algorand.co")["paymentRequirements"]
        proof = {
            "txId": "TEST_TX",
            "network": "algorand-testnet",
            "receiver": requirement["receiver"],
            "amountAtomic": "1",
            "asset": requirement["asset"],
            "resource": requirement["resource"],
            "paymentIntent": requirement["paymentIntent"],
            "policyHash": "a" * 64,
        }

        result = verify_payment_proof(proof, requirement, used_intents=set())

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "amountAtomic mismatch")


if __name__ == "__main__":
    unittest.main()
