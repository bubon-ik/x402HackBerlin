# Demo x402 Resource Server

Minimal x402-shaped protected resource for Hermes Sign402.

The server exposes:

```text
GET /probe?target=algorand.co
```

Without `X-Payment`, it returns:

```text
402 Payment Required
```

With a valid demo `X-Payment` proof, it returns the paid probe result.

## Run

```bash
cd demo-resource-server
python3 -m x402_demo
```

Default URL:

```text
http://127.0.0.1:8090
```

## Request Without Payment

```bash
curl -i "http://127.0.0.1:8090/probe?target=algorand.co"
```

Expected:

```http
HTTP/1.0 402 Payment Required
```

Example body:

```json
{
  "status": 402,
  "error": "payment_required",
  "x402Version": "demo-1",
  "accepts": ["X-Payment"],
  "paymentRequirements": {
    "scheme": "exact",
    "network": "algorand-testnet",
    "asset": "ALGO_TEST",
    "amountAtomic": "50000",
    "receiver": "DEMO_MERCHANT_ALGO_ADDRESS",
    "resource": "/probe?target=algorand.co",
    "paymentIntent": "intent-...",
    "purpose": "x402_api_access"
  }
}
```

`paymentIntent` is generated fresh for every unpaid `402 Payment Required` response. The server keeps that intent pending until a matching `X-Payment` proof is accepted. Reusing an accepted intent is rejected as replay.

## Request With Demo Payment Proof

For now, `X-Payment` is base64url JSON. The next step is replacing `txId: "DEMO_TX"` with a real Algorand TestNet transaction id.

```bash
python3 - <<'PY'
from x402_demo.core import build_payment_required, encode_payment_proof

requirement = build_payment_required("algorand.co")["paymentRequirements"]
proof = {
    "txId": "DEMO_TX",
    "network": requirement["network"],
    "receiver": requirement["receiver"],
    "amountAtomic": requirement["amountAtomic"],
    "asset": requirement["asset"],
    "resource": requirement["resource"],
    "paymentIntent": requirement["paymentIntent"],
    "policyHash": "f96440ece56ff3c056facaeb3923277dfd3cfc06d58775049c63aee32bc3656f"
}

print(encode_payment_proof(proof))
PY
```

Then:

```bash
curl -i "http://127.0.0.1:8090/probe?target=algorand.co" \
  -H "X-Payment: <PASTE_PAYMENT_PROOF>"
```

Expected:

```json
{
  "target": "algorand.co",
  "location": "Berlin",
  "httpStatus": 200,
  "latencyMs": 42,
  "paymentTx": "DEMO_TX",
  "result": "reachable"
}
```

## Real Algorand TestNet Proof Format

The server can also verify a real Algorand payment transaction through the public AlgoNode indexer.

The transaction must be an ALGO payment where:

- receiver equals `paymentRequirements.receiver`;
- amount equals `paymentRequirements.amountAtomic`;
- transaction is confirmed;
- note equals:

```text
sign402:<policyHash>:<paymentIntent>
```

Example `X-Payment` proof before base64url encoding:

```json
{
  "verificationMode": "algorand",
  "txId": "REAL_TESTNET_TX_ID",
  "network": "algorand-testnet",
  "receiver": "DEMO_MERCHANT_ALGO_ADDRESS",
  "amountAtomic": "50000",
  "asset": "ALGO_TEST",
  "resource": "/probe?target=algorand.co",
  "paymentIntent": "intent-cb77dc094504",
  "policyHash": "f96440ece56ff3c056facaeb3923277dfd3cfc06d58775049c63aee32bc3656f"
}
```

The resource server will look up the transaction on Algorand TestNet and reject the proof if receiver, amount, confirmation, or note commitment do not match.

Right after broadcast, the AlgoNode indexer may need a short moment before the transaction is queryable. Hermes should retry the final resource request with a small backoff, for example 2 seconds, before treating `payment_verification_failed` / transaction lookup `404` as final.

Mainnet is a config-level next step:

```json
{
  "network": "algorand-mainnet"
}
```

For hackathon safety, the first real settlement demo should use TestNet.

## Main Hermes Integration

The main hackathon demo does not expose this resource server directly to Hermes. The Sign402 Gateway calls it locally through `/agent/buy-probe`.

Hermes should use:

```text
POST <gateway-url>/agent/buy-probe
Content-Type: application/json

{"target":"algorand.co"}
```

The gateway handles the resource request, 402 handling, policy enforcement, Firefly approval, Algorand payment, X-Payment retry, and dashboard event.

## Low-Level Debug Prompt

Use this only when debugging the resource protocol without the short-mode gateway orchestration. Tell Hermes:

```text
Add Sign402 x402 resource demo.

When I write:
"request x402 probe for algorand.co"

Call:
GET http://127.0.0.1:8090/probe?target=algorand.co

When it returns 402, read paymentRequirements.

Load the saved Firefly-approved Sign402 policy.

Check:
- amountAtomic <= maxPerPaymentAtomic
- amountAtomic <= remaining budget
- asset matches policy.asset
- purpose matches policy.allowedPurpose
- paymentIntent not used
- policyHash equals firefly.approvedHash

For now, do not send real Algorand payment.
Create a demo X-Payment proof with txId "DEMO_TX" and retry the request.

Return:
- original 402 paymentRequirements
- policy decision
- retry result
- paymentIntent
- policyHash
```
