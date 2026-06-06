import base64
import json
import os
import secrets
from typing import Any

from .algorand import verify_algorand_payment_proof


PAYMENT_PRICE = "50000"
PAYMENT_ASSET = "ALGO_TEST"
PAYMENT_NETWORK = "algorand-testnet"
DEFAULT_MERCHANT_RECEIVER = "DEMO_MERCHANT_ALGO_ADDRESS"
PAYMENT_PURPOSE = "x402_api_access"


def build_payment_required(target: str) -> dict[str, Any]:
    resource = f"/probe?target={target}"
    payment_intent = _payment_intent_for(resource)
    return {
        "status": 402,
        "error": "payment_required",
        "x402Version": "demo-1",
        "accepts": ["X-Payment"],
        "paymentRequirements": {
            "scheme": "exact",
            "network": PAYMENT_NETWORK,
            "asset": PAYMENT_ASSET,
            "amountAtomic": PAYMENT_PRICE,
            "receiver": merchant_receiver(),
            "resource": resource,
            "paymentIntent": payment_intent,
            "purpose": PAYMENT_PURPOSE,
        },
    }


def encode_payment_proof(proof: dict[str, Any]) -> str:
    payload = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def parse_payment_proof(header_value: str) -> dict[str, Any]:
    try:
        padded = header_value + "=" * (-len(header_value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        proof = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid X-Payment proof. Expected base64url JSON.") from exc

    if not isinstance(proof, dict):
        raise ValueError("Invalid X-Payment proof. Expected JSON object.")
    return proof


def verify_payment_proof(
    proof: dict[str, Any],
    requirement: dict[str, Any],
    used_intents: set[str],
) -> dict[str, Any]:
    payment_intent = str(requirement["paymentIntent"])
    if payment_intent in used_intents:
        return {"ok": False, "reason": "paymentIntent already used"}

    required_matches = [
        ("network", "network mismatch"),
        ("receiver", "receiver mismatch"),
        ("amountAtomic", "amountAtomic mismatch"),
        ("asset", "asset mismatch"),
        ("resource", "resource mismatch"),
        ("paymentIntent", "paymentIntent mismatch"),
    ]

    for field, reason in required_matches:
        if str(proof.get(field)) != str(requirement.get(field)):
            return {"ok": False, "reason": reason}

    if not proof.get("txId"):
        return {"ok": False, "reason": "missing txId"}
    if not proof.get("policyHash"):
        return {"ok": False, "reason": "missing policyHash"}

    if proof.get("verificationMode") == "algorand":
        return verify_algorand_payment_proof(proof, requirement)

    return {"ok": True}


def build_probe_result(target: str, payment_proof: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": target,
        "location": "Berlin",
        "httpStatus": 200,
        "latencyMs": 42,
        "paymentTx": payment_proof["txId"],
        "paymentIntent": payment_proof["paymentIntent"],
        "policyHash": payment_proof["policyHash"],
        "result": "reachable",
    }


def _payment_intent_for(resource: str) -> str:
    return f"intent-{secrets.token_hex(8)}"


def merchant_receiver() -> str:
    return os.getenv("X402_MERCHANT_RECEIVER", DEFAULT_MERCHANT_RECEIVER)
