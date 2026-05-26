# Sign402 Gateway

Unified local Mac gateway for Hermes Sign402.

It combines:

- Firefly policy approval;
- Firefly payment approval;
- local Algorand TestNet payment execution.

Hermes gets one public tunnel URL and never receives private keys.

Implementation note: `/approve-policy` uses the Firefly `PAYMENT=<policyHash>` approval path. The older `POLICY=<policyHash>` firmware command can leave the device silent after approval on the current test unit, while `PAYMENT=<hash>` returns to the approval flow reliably.

## Endpoints

```text
GET  /health
POST /approve-policy
POST /approve-payment
POST /execute-payment
GET  /events/latest
POST /events/latest
POST /agent/buy-probe
```

## Main Demo Flow

For the normal hackathon demo, start all local services from the repository root:

```bash
cd "/Users/mp/Documents/Berlin Hack"
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
POST /agent/buy-probe
```

The resource server remains local. The gateway calls it directly.

## Manual Run

Install the only extra dependency into the payment executor venv:

```bash
"/Users/mp/Documents/Berlin Hack/payment-executor/.venv/bin/python" -m pip install pyserial
```

Check the Firefly port:

```bash
ls /dev/cu.usb*
```

Start the gateway:

```bash
cd "/Users/mp/Documents/Berlin Hack/sign402-gateway"
FIREFLY_PORT=/dev/cu.usbmodem11301 ../payment-executor/.venv/bin/python -m sign402_gateway
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
/Users/mp/Documents/Berlin Hack/demo-dashboard/latest-run.json
```

## Safety

- The gateway reads the Algorand private key from the local `payment-executor/.env`.
- The private key is never returned over HTTP.
- Hermes receives only payment metadata and `txId`.
- If Firefly approval fails, Hermes must not call `/execute-payment`.
- Dashboard events must contain only safe metadata, never private keys or mnemonics.
