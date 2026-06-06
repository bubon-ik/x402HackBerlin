# Sign402 Firefly Bridge

Local HTTP bridge between server-side Hermes and a Firefly device connected to this Mac.

Hermes sends a policy JSON to the bridge. The bridge canonicalizes it, computes a SHA-256 hash, sends the hash to Firefly with `POLICY=<64 hex chars>`, and returns the Firefly approval event.

For strict mode, Hermes can also send a payment commitment hash to `POST /approve-payment`. The bridge can first send `PAYMENT-CONTEXT=<line1>|<line2>|<line3>` and then sends `PAYMENT=<64 hex chars>` to Firefly. Firefly shows the human payment summary, the short payment hash, and waits for a physical approve/cancel button press.

## Run

Install dependencies, then run the bridge:

```bash
python3 -m pip install -e ./sign402-bridge
FIREFLY_PORT=/dev/cu.usbmodem11201 python3 -m sign402_bridge
```

Default URL:

```text
http://127.0.0.1:8088
```

Health check:

```bash
curl http://127.0.0.1:8088/health
```

## Approve A Policy

```bash
curl -X POST http://127.0.0.1:8088/approve-policy \
  -H "Content-Type: application/json" \
  -d '{
    "policy": {
      "version": "1",
      "agentId": "hermes-demo",
      "policyId": "policy-berlin-001",
      "allowedMerchant": "demo-merchant.local",
      "allowedPurpose": "x402_api_access",
      "asset": "ALGO_TEST",
      "maxBudgetAtomic": "1000000",
      "maxPerPaymentAtomic": "50000",
      "validFrom": "2026-06-06T09:00:00Z",
      "expiresAt": "2026-06-07T21:00:00Z",
      "nonce": "berlin-demo-001"
    }
  }'
```

Expected response shape:

```json
{
  "approved": true,
  "policyHash": "...",
  "firefly": {
    "approved": true,
    "approvedHash": "...",
    "deviceModel": 262,
    "deviceSerial": 1056,
    "raw": "..."
  }
}
```

The `policyHash` and `firefly.approvedHash` must be identical.

## Approve A Payment

```bash
curl -X POST http://127.0.0.1:8088/approve-payment \
  -H "Content-Type: application/json" \
  -d '{
    "paymentHash": "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
    "paymentContext": [
      "x402 WEATHER",
      "0.01 USDC",
      "GoPlausible API"
    ],
    "paymentCommitment": {
      "type": "sign402-payment",
      "policyHash": "...",
      "network": "algorand-testnet",
      "asset": "ALGO_TEST",
      "amountAtomic": "50000",
      "receiver": "MERCHANT",
      "resource": "/probe?target=algorand.co",
      "paymentIntent": "intent-001",
      "purpose": "x402_api_access"
    }
  }'
```

On Firefly:

- screen shows the payment summary, then short hash, then `OK / CANCEL`;
- approve button returns `approved: true`;
- cancel button returns `approved: false`;
- timeout returns `approved: false`.

## Tunnel For Server Hermes

Hermes lives on the server, while Firefly is connected to the Mac. For demo, expose this local bridge through a tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8088
```

Then configure server-side Hermes to call:

```text
POST https://your-tunnel-url/approve-policy
POST https://your-tunnel-url/approve-payment
```

## Notes

- The bridge intentionally fails if multiple `/dev/cu.usbmodem*` devices are found and `FIREFLY_PORT` is not set.
- This MVP uses Firefly as a hardware-visible approval/commitment device.
- Strict payment mode requires Firefly to be connected at payment time. If Firefly is disconnected, busy, rejected, or timed out, the payment must not be sent.
- `POLICY=` approval is not a cryptographic signature. DS `ATTEST` remains a future/stretch path.
