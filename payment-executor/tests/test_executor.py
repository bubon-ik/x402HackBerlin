import unittest
from unittest.mock import Mock, patch

from sign402_executor.executor import (
    build_x402_avm_payment_signature_header,
    build_payment_signature_header,
    build_payment_note,
    execute_payment,
    opt_in_asset,
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

    def test_build_payment_signature_header_builds_x402_avm_fee_payer_group(self):
        algod = Mock()
        algod.suggested_params.return_value = Mock(fee=1000, flat_fee=False)
        request = {
            "network": "algorand-testnet",
            "x402Network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
            "asset": "10458941",
            "receiver": "MERCHANT_ADDRESS",
            "amountAtomic": "10000",
            "paymentIntent": "x402-intent",
            "extra": {"feePayer": "FEE_PAYER_ADDRESS"},
        }
        signed_asset_txn = Mock()

        with patch("sign402_executor.executor.PaymentTxn") as payment_txn:
            with patch("sign402_executor.executor.AssetTransferTxn") as asset_transfer_txn:
                with patch("sign402_executor.executor.assign_group_id") as assign_group_id:
                    with patch("sign402_executor.executor.msgpack_encode") as msgpack_encode:
                        fee_txn = payment_txn.return_value
                        asset_txn = asset_transfer_txn.return_value
                        asset_txn.sign.return_value = signed_asset_txn
                        msgpack_encode.side_effect = ["FEE_TXN_B64", "SIGNED_ASSET_TXN_B64"]

                        result = build_payment_signature_header(
                            algod_client=algod,
                            sender="SENDER_ADDRESS",
                            private_key="PRIVATE_KEY",
                            payment_request=request,
                        )

        payment_txn.assert_called_once_with(
            sender="FEE_PAYER_ADDRESS",
            sp=payment_txn.call_args.kwargs["sp"],
            receiver="FEE_PAYER_ADDRESS",
            amt=0,
            note=b"x402-fee-payer",
        )
        asset_transfer_txn.assert_called_once_with(
            sender="SENDER_ADDRESS",
            sp=asset_transfer_txn.call_args.kwargs["sp"],
            receiver="MERCHANT_ADDRESS",
            amt=10000,
            index=10458941,
            note=b"x402-payment-v2",
        )
        self.assertEqual(asset_transfer_txn.call_args.kwargs["sp"].fee, 0)
        self.assertTrue(asset_transfer_txn.call_args.kwargs["sp"].flat_fee)
        assign_group_id.assert_called_once_with([fee_txn, asset_txn])
        asset_txn.sign.assert_called_once_with("PRIVATE_KEY")
        self.assertEqual(result["headerName"], "PAYMENT-SIGNATURE")
        self.assertEqual(result["payload"]["payload"]["paymentIndex"], 1)
        self.assertEqual(
            result["payload"]["payload"]["paymentGroup"],
            ["FEE_TXN_B64", "SIGNED_ASSET_TXN_B64"],
        )

    def test_build_x402_avm_payment_signature_header_filters_to_algorand_accept(self):
        payment_required = {
            "x402Version": 2,
            "resource": {"url": "https://x402.goplausible.xyz/examples/weather"},
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
                    "amount": "10000",
                    "asset": "10458941",
                    "payTo": "PAYEE",
                    "extra": {"feePayer": "FEEPAYER"},
                },
                {
                    "scheme": "exact",
                    "network": "eip155:84532",
                    "amount": "10000",
                    "asset": "0xTOKEN",
                },
            ],
        }

        class FakePaymentRequired:
            def __init__(self, accepts):
                self.accepts = [Mock(**accept) for accept in accepts]

            @classmethod
            def model_validate(cls, payload):
                return cls(payload["accepts"])

        with patch("sign402_executor.executor.PaymentRequired", FakePaymentRequired):
            with patch("sign402_executor.executor.x402ClientSync") as client_class:
                with patch("sign402_executor.executor.register_exact_avm_client") as register:
                    with patch("sign402_executor.executor.encode_payment_signature_header") as encode:
                        payload = Mock()
                        payload.model_dump.return_value = {"x402Version": 2}
                        client = client_class.return_value
                        client.create_payment_payload.return_value = payload
                        encode.return_value = "PAYMENT_SIGNATURE_HEADER"

                        result = build_x402_avm_payment_signature_header(
                            payment_required=payment_required,
                            sender="SENDER_ADDRESS",
                            private_key="PRIVATE_KEY",
                            algod_url="https://testnet-api.algonode.cloud",
                        )

        register.assert_called_once()
        created_payment_required = client.create_payment_payload.call_args.args[0]
        self.assertEqual(len(created_payment_required.accepts), 1)
        self.assertEqual(
            created_payment_required.accepts[0].network,
            "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
        )
        self.assertEqual(result["headerName"], "PAYMENT-SIGNATURE")
        self.assertEqual(result["headerValue"], "PAYMENT_SIGNATURE_HEADER")

    def test_opt_in_asset_submits_zero_amount_self_transfer(self):
        algod = Mock()
        algod.suggested_params.return_value = "SUGGESTED_PARAMS"
        algod.send_transaction.return_value = "OPTIN_TXID"
        signed_tx = Mock()

        with patch("sign402_executor.executor.AssetTransferTxn") as asset_transfer_txn:
            tx = asset_transfer_txn.return_value
            tx.sign.return_value = signed_tx
            result = opt_in_asset(
                algod_client=algod,
                sender="SENDER_ADDRESS",
                private_key="PRIVATE_KEY",
                asset_id=10458941,
            )

        asset_transfer_txn.assert_called_once_with(
            sender="SENDER_ADDRESS",
            sp="SUGGESTED_PARAMS",
            receiver="SENDER_ADDRESS",
            amt=0,
            index=10458941,
        )
        tx.sign.assert_called_once_with("PRIVATE_KEY")
        algod.send_transaction.assert_called_once_with(signed_tx)
        self.assertEqual(result, {"txId": "OPTIN_TXID", "assetId": "10458941"})


if __name__ == "__main__":
    unittest.main()
