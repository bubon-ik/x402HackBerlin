import base64
import unittest

from x402_demo.algorand import (
    build_sign402_note,
    extract_note_text,
    verify_algorand_payment_transaction,
)


class AlgorandVerifierTests(unittest.TestCase):
    def test_build_sign402_note_contains_policy_hash_and_intent(self):
        note = build_sign402_note("a" * 64, "intent-001")

        self.assertEqual(note, "sign402:a" * 0 + "sign402:" + "a" * 64 + ":intent-001")

    def test_extract_note_text_decodes_base64_note(self):
        note = base64.b64encode(b"sign402:test:intent").decode()

        self.assertEqual(extract_note_text(note), "sign402:test:intent")

    def test_verify_algorand_payment_transaction_accepts_matching_payment(self):
        requirement = {
            "network": "algorand-testnet",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "50000",
            "asset": "ALGO_TEST",
            "paymentIntent": "intent-001",
        }
        proof = {
            "txId": "TXID",
            "policyHash": "a" * 64,
            "paymentIntent": "intent-001",
        }
        tx = {
            "id": "TXID",
            "tx-type": "pay",
            "confirmed-round": 123,
            "note": base64.b64encode(
                build_sign402_note("a" * 64, "intent-001").encode()
            ).decode(),
            "payment-transaction": {
                "receiver": "MERCHANT_ADDRESS",
                "amount": 50000,
            },
        }

        result = verify_algorand_payment_transaction(tx, proof, requirement)

        self.assertTrue(result["ok"])

    def test_verify_algorand_payment_transaction_rejects_wrong_receiver(self):
        requirement = {
            "network": "algorand-testnet",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "50000",
            "asset": "ALGO_TEST",
            "paymentIntent": "intent-001",
        }
        proof = {
            "txId": "TXID",
            "policyHash": "a" * 64,
            "paymentIntent": "intent-001",
        }
        tx = {
            "id": "TXID",
            "tx-type": "pay",
            "confirmed-round": 123,
            "note": base64.b64encode(
                build_sign402_note("a" * 64, "intent-001").encode()
            ).decode(),
            "payment-transaction": {
                "receiver": "OTHER_ADDRESS",
                "amount": 50000,
            },
        }

        result = verify_algorand_payment_transaction(tx, proof, requirement)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "receiver mismatch")

    def test_verify_algorand_payment_transaction_rejects_missing_note_commitment(self):
        requirement = {
            "network": "algorand-testnet",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "50000",
            "asset": "ALGO_TEST",
            "paymentIntent": "intent-001",
        }
        proof = {
            "txId": "TXID",
            "policyHash": "a" * 64,
            "paymentIntent": "intent-001",
        }
        tx = {
            "id": "TXID",
            "tx-type": "pay",
            "confirmed-round": 123,
            "note": base64.b64encode(b"not-sign402").decode(),
            "payment-transaction": {
                "receiver": "MERCHANT_ADDRESS",
                "amount": 50000,
            },
        }

        result = verify_algorand_payment_transaction(tx, proof, requirement)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "note commitment mismatch")


if __name__ == "__main__":
    unittest.main()
