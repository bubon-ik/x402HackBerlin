# Sign402 Algorand Payment Executor

Small CLI/library for sending the Algorand TestNet payment required by the demo x402 resource server.

It sends a normal ALGO payment with this note:

```text
sign402:<policyHash>:<paymentIntent>
```

The x402 verifier can then look up the transaction and verify receiver, amount, confirmation, and note commitment.

## Install Dependency

```bash
python3 -m pip install py-algorand-sdk
```

## Required Environment

```bash
export ALGORAND_SENDER="YOUR_TESTNET_ADDRESS"
export ALGORAND_PRIVATE_KEY="YOUR_ALGOSDK_PRIVATE_KEY"
export ALGOD_URL="https://testnet-api.algonode.cloud"
```

`ALGORAND_PRIVATE_KEY` is the SDK private key string, not the 25-word mnemonic. Keep it out of git.

## Payment Request Example

Create `payment-request.json` from the `paymentRequirements` returned by:

```bash
curl "http://127.0.0.1:8090/probe?target=algorand.co"
```

Example:

```json
{
  "scheme": "exact",
  "network": "algorand-testnet",
  "asset": "ALGO_TEST",
  "amountAtomic": "50000",
  "receiver": "DEMO_MERCHANT_ALGO_ADDRESS",
  "resource": "/probe?target=algorand.co",
  "paymentIntent": "intent-cb77dc094504",
  "purpose": "x402_api_access"
}
```

For a real transaction, replace `DEMO_MERCHANT_ALGO_ADDRESS` with a funded TestNet receiver address you control.

## Send Payment

```bash
PYTHONPATH=payment-executor python3 -m sign402_executor \
  --payment-request payment-request.json \
  --policy-hash f96440ece56ff3c056facaeb3923277dfd3cfc06d58775049c63aee32bc3656f
```

Output:

```json
{
  "txId": "REAL_TESTNET_TX_ID",
  "network": "algorand-testnet",
  "receiver": "...",
  "amountAtomic": "50000",
  "asset": "ALGO_TEST",
  "paymentIntent": "intent-cb77dc094504",
  "policyHash": "...",
  "note": "sign402:<policyHash>:<paymentIntent>"
}
```

## Use Tx In X-Payment

Build an `X-Payment` proof:

```json
{
  "verificationMode": "algorand",
  "txId": "REAL_TESTNET_TX_ID",
  "network": "algorand-testnet",
  "receiver": "...",
  "amountAtomic": "50000",
  "asset": "ALGO_TEST",
  "resource": "/probe?target=algorand.co",
  "paymentIntent": "intent-cb77dc094504",
  "policyHash": "..."
}
```

Base64url encode that JSON and retry:

```bash
curl "http://127.0.0.1:8090/probe?target=algorand.co" \
  -H "X-Payment: <BASE64URL_JSON_PROOF>"
```

## Mainnet

The executor is intentionally TestNet-first. Mainnet should be a config-level milestone after the TestNet x402 flow is stable.
