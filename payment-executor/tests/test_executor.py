import unittest
from unittest.mock import Mock, patch

from sign402_executor.executor import (
    build_payment_note,
    execute_payment,
    validate_payment_request,
)


class ExecutorTests(unittest.TestCase):
    def test_build_payment_note(self):
        note = build_payment_note("a" * 64, "intent-001")

        self.assertEqual(note, b"sign402:" + b"a" * 64 + b":intent-001")

    def test_validate_payment_request_accepts_algo_test_payment(self):
        request = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "50000",
            "paymentIntent": "intent-001",
        }

        validate_payment_request(request, "a" * 64)

    def test_validate_payment_request_rejects_non_algo_asset(self):
        request = {
            "network": "algorand-testnet",
            "asset": "USDC_TEST",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "50000",
            "paymentIntent": "intent-001",
        }

        with self.assertRaises(ValueError) as error:
            validate_payment_request(request, "a" * 64)

        self.assertIn("Only ALGO_TEST is supported", str(error.exception))

    def test_execute_payment_builds_and_submits_algorand_tx(self):
        algod = Mock()
        algod.suggested_params.return_value = "SUGGESTED_PARAMS"
        algod.send_transaction.return_value = "TXID"
        signed_tx = Mock()

        request = {
            "network": "algorand-testnet",
            "asset": "ALGO_TEST",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "50000",
            "paymentIntent": "intent-001",
        }

        with patch("sign402_executor.executor.PaymentTxn") as payment_txn:
            tx = payment_txn.return_value
            tx.sign.return_value = signed_tx
            result = execute_payment(
                algod_client=algod,
                sender="SENDER_ADDRESS",
                private_key="PRIVATE_KEY",
                payment_request=request,
                policy_hash="a" * 64,
            )

        payment_txn.assert_called_once_with(
            sender="SENDER_ADDRESS",
            sp="SUGGESTED_PARAMS",
            receiver="MERCHANT_ADDRESS",
            amt=50000,
            note=b"sign402:" + b"a" * 64 + b":intent-001",
        )
        tx.sign.assert_called_once_with("PRIVATE_KEY")
        algod.send_transaction.assert_called_once_with(signed_tx)
        self.assertEqual(result["txId"], "TXID")
        self.assertEqual(result["note"], "sign402:" + "a" * 64 + ":intent-001")


if __name__ == "__main__":
    unittest.main()
