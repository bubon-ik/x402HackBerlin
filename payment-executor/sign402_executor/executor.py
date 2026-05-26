import re
from typing import Any

try:
    from algosdk.transaction import PaymentTxn
except ImportError:  # pragma: no cover - tested through mocks/import fallback
    PaymentTxn = None


SUPPORTED_NETWORK = "algorand-testnet"
SUPPORTED_ASSET = "ALGO_TEST"


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

