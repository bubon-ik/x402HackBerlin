import re
import base64
import copy
import json
from typing import Any

try:
    from algosdk.encoding import msgpack_encode
    from algosdk.transaction import AssetTransferTxn, PaymentTxn, assign_group_id
except ImportError:  # pragma: no cover - tested through mocks/import fallback
    AssetTransferTxn = None
    PaymentTxn = None
    assign_group_id = None
    msgpack_encode = None

try:
    from x402 import PaymentRequired, x402ClientSync
    from x402.http import encode_payment_signature_header
    from x402.mechanisms.avm.exact import register_exact_avm_client
except ImportError:  # pragma: no cover - optional official x402 path
    PaymentRequired = None
    x402ClientSync = None
    encode_payment_signature_header = None
    register_exact_avm_client = None


SUPPORTED_NETWORK = "algorand-testnet"
SUPPORTED_ASSET = "ALGO_TEST"
ALGORAND_TESTNET_CAIP2 = "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="
USDC_TESTNET_ASA_ID = "10458941"


def build_payment_note(policy_hash: str, payment_intent: str) -> bytes:
    return f"sign402:{policy_hash}:{payment_intent}".encode("utf-8")


def validate_payment_request(payment_request: dict[str, Any], policy_hash: str) -> None:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", policy_hash):
        raise ValueError("policy_hash must be 64 hex characters.")
    if payment_request.get("network") != SUPPORTED_NETWORK:
        raise ValueError(f"Only {SUPPORTED_NETWORK} is supported for this demo.")
    if payment_request.get("asset") != SUPPORTED_ASSET:
        raise ValueError("Only ALGO_TEST is supported for the first executor demo.")
    if not payment_request.get("receiver"):
        raise ValueError("payment_request.receiver is required.")
    if not payment_request.get("paymentIntent"):
        raise ValueError("payment_request.paymentIntent is required.")

    amount = int(str(payment_request.get("amountAtomic", "0")))
    if amount <= 0:
        raise ValueError("payment_request.amountAtomic must be positive.")


def validate_x402_avm_payment_request(payment_request: dict[str, Any]) -> None:
    if payment_request.get("network") != SUPPORTED_NETWORK:
        raise ValueError(f"Only {SUPPORTED_NETWORK} is supported.")
    if str(payment_request.get("asset")) != USDC_TESTNET_ASA_ID:
        raise ValueError(f"Only USDC TestNet ASA {USDC_TESTNET_ASA_ID} is supported.")
    if not payment_request.get("receiver"):
        raise ValueError("payment_request.receiver is required.")
    amount = int(str(payment_request.get("amountAtomic", "0")))
    if amount <= 0:
        raise ValueError("payment_request.amountAtomic must be positive.")


def build_payment_signature_header(
    *,
    algod_client,
    sender: str,
    private_key: str,
    payment_request: dict[str, Any],
) -> dict[str, Any]:
    validate_x402_avm_payment_request(payment_request)

    if AssetTransferTxn is None or PaymentTxn is None or assign_group_id is None or msgpack_encode is None:
        raise RuntimeError("py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk")

    amount = int(str(payment_request["amountAtomic"]))
    asset_id = int(str(payment_request["asset"]))
    receiver = str(payment_request["receiver"])
    x402_network = str(payment_request.get("x402Network") or ALGORAND_TESTNET_CAIP2)
    extra = payment_request.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}

    txns: list[Any] = []
    payment_index = 0

    fee_payer = extra.get("feePayer")
    if fee_payer:
        fee_params = copy.copy(algod_client.suggested_params())
        fee_params.flat_fee = True
        fee_params.fee = max(int(getattr(fee_params, "fee", 1000) or 1000), 1000) * 2
        fee_txn = PaymentTxn(
            sender=str(fee_payer),
            sp=fee_params,
            receiver=str(fee_payer),
            amt=0,
            note=b"x402-fee-payer",
        )
        txns.append(fee_txn)
        payment_index = 1

    asset_params = copy.copy(algod_client.suggested_params())
    if fee_payer:
        asset_params.flat_fee = True
        asset_params.fee = 0
    asset_txn = AssetTransferTxn(
        sender=sender,
        sp=asset_params,
        receiver=receiver,
        amt=amount,
        index=asset_id,
        note=b"x402-payment-v2",
    )
    txns.append(asset_txn)

    assign_group_id(txns)
    signed_asset_txn = asset_txn.sign(private_key)
    payment_group = []
    for index, txn in enumerate(txns):
        if index == payment_index:
            payment_group.append(msgpack_encode(signed_asset_txn))
        else:
            payment_group.append(msgpack_encode(txn))

    payload = {
        "x402Version": 2,
        "scheme": "exact",
        "network": x402_network,
        "payload": {
            "paymentGroup": payment_group,
            "paymentIndex": payment_index,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "headerName": "PAYMENT-SIGNATURE",
        "headerValue": base64.b64encode(canonical.encode("utf-8")).decode("ascii"),
        "payload": payload,
    }


class AlgoSdkPrivateKeySigner:
    def __init__(self, address: str, private_key: str):
        self._address = address
        self._private_key = private_key

    @property
    def address(self) -> str:
        return self._address

    def sign_transactions(
        self,
        unsigned_txns: list[bytes],
        indexes_to_sign: list[int],
    ) -> list[bytes | None]:
        if msgpack_encode is None:
            raise RuntimeError("py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk")

        indexes = set(indexes_to_sign)
        signed: list[bytes | None] = []
        for index, raw_txn in enumerate(unsigned_txns):
            if index not in indexes:
                signed.append(None)
                continue
            txn = _transaction_from_msgpack(raw_txn)
            signed_txn = txn.sign(self._private_key)
            signed.append(base64.b64decode(msgpack_encode(signed_txn)))
        return signed


def build_x402_avm_payment_signature_header(
    *,
    payment_required: dict[str, Any],
    sender: str,
    private_key: str,
    algod_url: str,
) -> dict[str, Any]:
    if PaymentRequired is None or x402ClientSync is None or register_exact_avm_client is None:
        raise RuntimeError('x402-avm is required. Install with: python3 -m pip install "x402-avm[avm,requests]"')
    if encode_payment_signature_header is None:
        raise RuntimeError("x402-avm HTTP helpers are required.")

    avm_payment_required = dict(payment_required)
    accepts = avm_payment_required.get("accepts")
    if not isinstance(accepts, list):
        raise ValueError("payment_required.accepts must be a list")
    avm_accepts = [
        accept
        for accept in accepts
        if isinstance(accept, dict) and str(accept.get("network", "")).startswith("algorand:")
    ]
    if not avm_accepts:
        raise ValueError("payment_required.accepts does not include an Algorand payment option")
    avm_payment_required["accepts"] = avm_accepts

    client = x402ClientSync()
    register_exact_avm_client(
        client,
        AlgoSdkPrivateKeySigner(sender, private_key),
        algod_url=algod_url,
    )
    payment_payload = client.create_payment_payload(PaymentRequired.model_validate(avm_payment_required))
    return {
        "headerName": "PAYMENT-SIGNATURE",
        "headerValue": encode_payment_signature_header(payment_payload),
        "payload": payment_payload.model_dump(by_alias=True, exclude_none=True),
    }


def _transaction_from_msgpack(raw_txn: bytes):
    if msgpack_encode is None:
        raise RuntimeError("py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk")
    from algosdk import encoding
    from algosdk.transaction import Transaction

    return Transaction.undictify(encoding.msgpack.unpackb(raw_txn, raw=False))


def execute_payment(
    *,
    algod_client,
    sender: str,
    private_key: str,
    payment_request: dict[str, Any],
    policy_hash: str,
) -> dict[str, Any]:
    validate_payment_request(payment_request, policy_hash)

    if PaymentTxn is None:
        raise RuntimeError("py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk")

    amount = int(str(payment_request["amountAtomic"]))
    payment_intent = str(payment_request["paymentIntent"])
    note = build_payment_note(policy_hash.lower(), payment_intent)

    tx = PaymentTxn(
        sender=sender,
        sp=algod_client.suggested_params(),
        receiver=str(payment_request["receiver"]),
        amt=amount,
        note=note,
    )
    signed_tx = tx.sign(private_key)
    tx_id = algod_client.send_transaction(signed_tx)

    return {
        "txId": tx_id,
        "network": payment_request["network"],
        "receiver": payment_request["receiver"],
        "amountAtomic": str(amount),
        "asset": payment_request["asset"],
        "paymentIntent": payment_intent,
        "policyHash": policy_hash.lower(),
        "note": note.decode("utf-8"),
    }


def opt_in_asset(
    *,
    algod_client,
    sender: str,
    private_key: str,
    asset_id: int,
) -> dict[str, str]:
    if AssetTransferTxn is None:
        raise RuntimeError("py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk")

    tx = AssetTransferTxn(
        sender=sender,
        sp=algod_client.suggested_params(),
        receiver=sender,
        amt=0,
        index=int(asset_id),
    )
    signed_tx = tx.sign(private_key)
    tx_id = algod_client.send_transaction(signed_tx)
    return {"txId": tx_id, "assetId": str(asset_id)}


def execute_asset_transfer(
    *,
    algod_client,
    sender: str,
    private_key: str,
    receiver: str,
    asset_id: int,
    amount_atomic: int,
    note: bytes | None = None,
    network: str = "algorand-mainnet",
    asset_name: str = "ASA",
) -> dict[str, Any]:
    if AssetTransferTxn is None:
        raise RuntimeError("py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk")
    if amount_atomic <= 0:
        raise ValueError("amount_atomic must be positive")
    if not receiver:
        raise ValueError("receiver is required")

    tx_kwargs: dict[str, Any] = {
        "sender": sender,
        "sp": algod_client.suggested_params(),
        "receiver": receiver,
        "amt": int(amount_atomic),
        "index": int(asset_id),
    }
    if note is not None:
        tx_kwargs["note"] = note

    tx = AssetTransferTxn(**tx_kwargs)
    signed_tx = tx.sign(private_key)
    tx_id = algod_client.send_transaction(signed_tx)
    return {
        "txId": tx_id,
        "network": network,
        "receiver": receiver,
        "amountAtomic": str(int(amount_atomic)),
        "asset": asset_name,
        "assetId": str(int(asset_id)),
        "note": note.decode("utf-8") if note else "",
    }
