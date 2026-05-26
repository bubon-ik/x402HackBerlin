# Hermes Sign402 Demo Script

## Goal

Show that Hermes can buy an official GoPlausible x402-protected API on Algorand from Telegram, while Firefly remains mandatory for policy approval and exact payment approval.

## Before The Pitch

Connect Firefly over USB-C and check the port:

```bash
ls /dev/cu.usb*
```

Start the local stack:

```bash
cd "/Users/mp/Documents/Berlin Hack"
bash scripts/start-local-demo.sh
```

Open the dashboard:

```text
http://127.0.0.1:8100
```

Expose the Sign402 Gateway:

```bash
cloudflared tunnel --url http://127.0.0.1:8099
```

Give Hermes the new gateway URL:

```text
Use Sign402 Gateway:
https://<gateway-tunnel>.trycloudflare.com

For policy approval, call POST /approve-policy.
For buying GoPlausible weather, call POST /agent/buy-x402 with {"url":"https://x402.goplausible.xyz/examples/weather"}.
Do not build the x402 payment yourself. Do not ask for private keys. Only call the Sign402 Gateway.
```

## Stage Flow

### 1. Explain The Problem

Say:

```text
x402 lets agents pay for web resources. Sign402 adds the missing consent layer: the agent can act autonomously, but payments are bounded by a hardware-approved policy and each live payment needs physical Firefly approval.
```

### 2. Approve Policy

In Telegram:

```text
approve sign402 policy
```

Use the official USDC policy:

```json
{
  "version": "1",
  "agentId": "hermes-demo",
  "policyId": "policy-goplausible-usdc-demo",
  "allowedPurpose": "x402_api_access",
  "asset": "10458941",
  "maxBudgetAtomic": "100000",
  "maxPerPaymentAtomic": "10000",
  "nonce": "goplausible-weather-demo"
}
```

Expected:

- Firefly shows the policy hash.
- User presses approve.
- Hermes replies that policy is approved.
- Dashboard shows policy hash and Firefly device identity.

### 3. Buy Resource

In Telegram:

```text
buy goplausible weather
```

Expected:

- Gateway requests `https://x402.goplausible.xyz/examples/weather`.
- GoPlausible returns `402 Payment Required`.
- Gateway checks the stored policy.
- Firefly shows `x402 WEATHER`, `0.01 USDC`, `GoPlausible API`, and the short payment approval hash.
- User presses approve.
- Gateway creates official `x402-avm` `PAYMENT-SIGNATURE`.
- GoPlausible facilitator settles the Algorand TestNet USDC payment.
- GoPlausible returns protected weather JSON.
- Hermes replies with decision, tx id, policy hash, payment hash, weather result, and remaining budget.
- Dashboard updates automatically.

### 4. Point To The Audit Trail

Show:

- Telegram command;
- Firefly hash on device;
- dashboard payment approval hash;
- Algorand tx id;
- official GoPlausible `Payment-Response`;
- protected weather JSON.

Say:

```text
The agent did not get the private key. It could only trigger a payment after the gateway checked the USDC policy and Firefly approved the exact payment hash. The final API response came from a real GoPlausible x402 resource.
```

## Failure Demo

Optional if time allows:

- Disconnect Firefly or press cancel.
- Run `buy goplausible weather` again.
- Expected result: payment rejected, no Algorand transaction and no protected API response.

Say:

```text
Without Firefly approval, Hermes cannot execute the payment.
```

## Backup

If Cloudflare quick tunnel changes, run it again and give Hermes only the new gateway URL.

If a port is busy:

```bash
lsof -nP -iTCP:8099 -sTCP:LISTEN
lsof -nP -iTCP:8100 -sTCP:LISTEN
```

Stop the old process or restart the terminal session, then run:

```bash
cd "/Users/mp/Documents/Berlin Hack"
bash scripts/start-local-demo.sh
```
