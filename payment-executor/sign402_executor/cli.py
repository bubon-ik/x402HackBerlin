import argparse
import json
import os
import sys

from .executor import execute_payment


DEFAULT_ALGOD = "https://testnet-api.algonode.cloud"


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Sign402 Algorand TestNet payment.")
    parser.add_argument("--payment-request", required=True, help="Path to payment request JSON.")
    parser.add_argument("--policy-hash", required=True)
    parser.add_argument("--algod-url", default=os.getenv("ALGOD_URL", DEFAULT_ALGOD))
    parser.add_argument("--sender", default=os.getenv("ALGORAND_SENDER"))
    parser.add_argument("--private-key", default=os.getenv("ALGORAND_PRIVATE_KEY"))
    args = parser.parse_args()

    if not args.sender:
        raise SystemExit("Missing ALGORAND_SENDER or --sender.")
    if not args.private_key:
        raise SystemExit("Missing ALGORAND_PRIVATE_KEY or --private-key.")

    try:
        from algosdk.v2client.algod import AlgodClient
    except ImportError as exc:
        raise SystemExit(
            "py-algorand-sdk is required. Install with: python3 -m pip install py-algorand-sdk"
        ) from exc

    with open(args.payment_request, "r", encoding="utf-8") as file:
        payment_request = json.load(file)

    algod_client = AlgodClient("", args.algod_url)
    result = execute_payment(
        algod_client=algod_client,
        sender=args.sender,
        private_key=args.private_key,
        payment_request=payment_request,
        policy_hash=args.policy_hash,
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

