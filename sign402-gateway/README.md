# Sign402 Gateway

Unified local Mac gateway for Hermes Sign402.

It combines:

- Firefly policy approval;
- Firefly payment approval;
- local Algorand TestNet payment execution.

Hermes gets one public tunnel URL and never receives private keys.

Implementation note: `/approve-policy` uses the Firefly `PAYMENT=<policyHash>` approval path. The older `POLICY=<policyHash>` firmware command can leave the device silent after approval on the current test unit, while `PAYMENT=<hash>` returns to the approval flow reliably.

Payment approval uses the Firefly `PAYMENT-CONTEXT=<line1>|<line2>|<line3>` pre-command when context is available. The current GoPlausible demo shows:

```text
x402 WEATHER
0.01 USDC
GoPlausible API
Hash ....a1ef
OK / CANCEL
```

The paid QR tool overrides only the human-readable Firefly context:

```text
x402 QR CODE
0.01 USDC
Sign402 Generator
Hash ....a1ef
OK / CANCEL
```

The payment commitment, approved hash, x402 settlement, and policy checks remain unchanged.

## Endpoints

```text
GET  /health
POST /approve-policy
POST /approve-payment
POST /execute-payment
GET  /events/latest
POST /events/latest
POST /agent/buy-probe
GET  /agent/tools
POST /agent/inspect-tool
POST /agent/buy-tool
POST /agent/inspect-x402
POST /agent/buy-x402
```

## Main Demo Flow

For the normal hackathon demo, start all local services from the repository root:

```bash
./scripts/start-local-demo.sh
```

Then expose only the gateway:

```bash
cloudflared tunnel --url http://127.0.0.1:8099
```

Give Hermes the resulting base URL:

```text
SIGN402_GATEWAY_URL=https://<tunnel>.trycloudflare.com
```

Hermes uses two product endpoints:

```text
POST /approve-policy
POST /agent/buy-tool
```

Hermes can inspect and buy paid tools:

```bash
curl -sS http://127.0.0.1:8099/agent/tools

curl -sS -X POST http://127.0.0.1:8099/agent/inspect-tool \
  -H "Content-Type: application/json" \
  -d '{"tool":"goplausible.weather"}'

curl -sS -X POST http://127.0.0.1:8099/agent/buy-tool \
  -H "Content-Type: application/json" \
  -d '{"tool":"goplausible.weather"}'

curl -sS -X POST http://127.0.0.1:8099/agent/buy-tool \
  -H "Content-Type: application/json" \
  -d '{"tool":"qr","url":"https://github.com/bubon-ik/x402HackBerlin"}'
```

The paid-tool endpoints wrap the official `/agent/buy-x402` payment path so the agent workflow is tool-oriented rather than URL-oriented. The QR tool uses the same Firefly-approved x402 payment flow, then returns a compact Telegram receipt and a `qrImageUrl` artifact. `/agent/buy-probe` remains available for the local probe demo.

## Manual Run

Install the package dependencies:

```bash
python3 -m pip install -e ./sign402-gateway
```

Check the Firefly port:

```bash
ls /dev/cu.usb*
```

Start the gateway:

```bash
FIREFLY_PORT=/dev/cu.usbmodem11301 python3 -m sign402_gateway
```

Default URL:

```text
http://127.0.0.1:8099
```

Expose one tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8099
```

Give Hermes the resulting base URL:

```text
SIGN402_GATEWAY_URL=https://<tunnel>.trycloudflare.com
```

## Agent Buy Probe

This is the short UX endpoint for Hermes. After a policy has been approved through `/approve-policy`, Hermes can call one endpoint:

```bash
curl -X POST http://127.0.0.1:8099/agent/buy-probe \
  -H "Content-Type: application/json" \
  -d '{"target":"algorand.co"}'
```

The gateway handles the full flow:

```text
GET resource -> 402 -> policy check -> Firefly PAYMENT approval -> Algorand payment -> X-Payment retry -> dashboard event
```

Hermes receives the final public result and never receives private keys.

## Low-Level Payment Execution

This endpoint is kept for protocol debugging and tests. In the main short-mode demo, Hermes calls `/agent/buy-probe` instead, and the gateway performs payment approval plus execution internally.

If you use the low-level flow manually, call this only after Firefly approved the payment hash.

```bash
curl -X POST http://127.0.0.1:8099/execute-payment \
  -H "Content-Type: application/json" \
  -d '{
    "policyHash": "<64 hex chars>",
    "paymentApprovalHash": "<64 hex chars>",
    "paymentRequirements": {
      "network": "algorand-testnet",
      "asset": "ALGO_TEST",
      "amountAtomic": "50000",
      "receiver": "MERCHANT_ALGO_ADDRESS",
      "resource": "/probe?target=algorand.co",
      "paymentIntent": "intent-001",
      "purpose": "x402_api_access"
    }
  }'
```

Expected response:

```json
{
  "ok": true,
  "policyHash": "...",
  "paymentApprovalHash": "...",
  "payment": {
    "txId": "...",
    "network": "algorand-testnet",
    "receiver": "...",
    "amountAtomic": "50000",
    "asset": "ALGO_TEST",
    "paymentIntent": "...",
    "policyHash": "...",
    "note": "sign402:<policyHash>:<paymentIntent>"
  }
}
```

## Live Dashboard Event

The dashboard polls the gateway for the latest safe run event:

```text
GET /events/latest
```

In the main short-mode demo, `/agent/buy-probe` writes this event automatically.

For low-level debugging, a client can update the dashboard manually after a completed flow:

```bash
curl -X POST http://127.0.0.1:8099/events/latest \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "decision": "APPROVED & EXECUTED",
      "policyHash": "<64 hex chars>",
      "paymentApprovalHash": "<64 hex chars>",
      "txId": "<algorand tx id>",
      "resource": "/probe?target=algorand.co",
      "paymentIntent": "intent-001",
      "amountAtomic": "50000",
      "asset": "ALGO_TEST",
      "network": "algorand-testnet",
      "deviceModel": 262,
      "deviceSerial": 1056,
      "remainingBudgetAtomic": "950000",
      "resourceResult": {
        "target": "algorand.co",
        "location": "Berlin",
        "httpStatus": 200,
        "latencyMs": 42,
        "result": "reachable"
      }
    }
  }'
```

The default event store is:

```text
demo-dashboard/latest-run.json
```

## Safety

- The gateway reads the Algorand private key from the local `payment-executor/.env`.
- The private key is never returned over HTTP.
- Hermes receives only payment metadata and `txId`.
- If Firefly approval fails, Hermes must not call `/execute-payment`.
- Dashboard events must contain only safe metadata, never private keys or mnemonics.
