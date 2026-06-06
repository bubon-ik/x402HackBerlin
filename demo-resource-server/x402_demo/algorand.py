import base64
import json
import urllib.error
import urllib.request
from typing import Any


DEFAULT_INDEXER_URLS = {
    "algorand-testnet": "https://testnet-idx.algonode.cloud",
    "algorand-mainnet": "https://mainnet-idx.algonode.cloud",
}


def build_sign402_note(policy_hash: str, payment_intent: str) -> str:
    return f"sign402:{policy_hash}:{payment_intent}"


def extract_note_text(note: str | None) -> str:
    if not note:
        return ""
    try:
        return base64.b64decode(note).decode("utf-8")
    except Exception:
        return ""


def fetch_algorand_transaction(tx_id: str, network: str) -> dict[str, Any]:
    base_url = DEFAULT_INDEXER_URLS.get(network)
    if not base_url:
        raise ValueError(f"Unsupported Algorand network: {network}")

    url = f"{base_url}/v2/transactions/{tx_id}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Algorand transaction lookup failed: HTTP {exc.code}") from exc
    except Exception as exc:
        raise ValueError(f"Algorand transaction lookup failed: {exc}") from exc

    transaction = payload.get("transaction")
    if not isinstance(transaction, dict):
        raise ValueError("Algorand indexer response did not contain transaction.")
    return transaction


def verify_algorand_payment_transaction(
    transaction: dict[str, Any],
    proof: dict[str, Any],
    requirement: dict[str, Any],
) -> dict[str, Any]:
    if transaction.get("id") != proof.get("txId"):
        return {"ok": False, "reason": "txId mismatch"}
    if transaction.get("tx-type") != "pay":
        return {"ok": False, "reason": "transaction is not ALGO payment"}
    if not transaction.get("confirmed-round"):
        return {"ok": False, "reason": "transaction is not confirmed"}

    payment = transaction.get("payment-transaction") or {}
    if payment.get("receiver") != requirement.get("receiver"):
        return {"ok": False, "reason": "receiver mismatch"}
    if str(payment.get("amount")) != str(requirement.get("amountAtomic")):
        return {"ok": False, "reason": "amountAtomic mismatch"}

    expected_note = build_sign402_note(
        str(proof.get("policyHash", "")),
        str(requirement.get("paymentIntent", "")),
    )
    actual_note = extract_note_text(transaction.get("note"))
    if actual_note != expected_note:
        return {"ok": False, "reason": "note commitment mismatch"}

    return {
        "ok": True,
        "confirmedRound": transaction["confirmed-round"],
        "sender": transaction.get("sender"),
    }


def verify_algorand_payment_proof(
    proof: dict[str, Any],
    requirement: dict[str, Any],
) -> dict[str, Any]:
    tx_id = proof.get("txId")
    if not tx_id:
        return {"ok": False, "reason": "missing txId"}

    try:
        transaction = fetch_algorand_transaction(str(tx_id), str(requirement.get("network")))
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}

    return verify_algorand_payment_transaction(transaction, proof, requirement)
