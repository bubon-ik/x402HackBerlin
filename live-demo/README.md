# Hermes Sign402 Live Demo

This folder ties the pieces together:

```text
Firefly-approved policyHash
  -> x402 resource request
  -> HTTP 402 Payment Required
  -> Firefly payment approval
  -> Algorand TestNet payment
  -> X-Payment retry
  -> on-chain verification
  -> resource access
```

## Terminal 1: Firefly Bridge

```bash
PYTHONPATH=sign402-bridge FIREFLY_PORT=/dev/cu.usbmodem11301 python3 -m sign402_bridge
```

If the Firefly port changes:

```bash
ls /dev/cu.usb*
```

## Terminal 2: Cloudflare Tunnel

```bash
cloudflared tunnel --url http://127.0.0.1:8088
```

Give the resulting URL to Hermes:

```text
https://<tunnel>.trycloudflare.com/approve-policy
https://<tunnel>.trycloudflare.com/approve-payment
```

## Terminal 3: x402 Resource Server

```bash
PYTHONPATH=demo-resource-server X402_MERCHANT_RECEIVER=ERUMW536MUKV7T2JHM35HUQADFIW4SLELUPBNVR4CBJH34WRD7XMHADD6A python3 -m x402_demo
```

## Step 1: Fresh Firefly Approval

Ask Hermes:

```text
Create a NEW Sign402 policy now.
Do not use cached approval.
Call the current Sign402 bridge endpoint.
Return policyHash, deviceModel, and deviceSerial.
```

Confirm the hash on Firefly matches Hermes.

## Step 2: Run Paid Probe

Use the `policyHash` from Hermes. For strict Firefly mode, pass the local bridge URL:

```bash
PYTHONPATH=live-demo:payment-executor python3 -m sign402_live \
  --policy-hash <POLICY_HASH_FROM_HERMES> \
  --payment-executor-dir payment-executor \
  --resource-url http://127.0.0.1:8090 \
  --firefly-bridge-url http://127.0.0.1:8088 \
  --target algorand.co
```

Firefly will show a payment hash before the Algorand transaction is sent. Press approve to continue or cancel to stop. If Firefly is disconnected, rejected, busy, or times out, the runner stops before sending payment.

Expected output:

```json
{
  "status": "access_granted",
  "paymentApproval": {
    "approved": true
  },
  "payment": {
    "txId": "REAL_TESTNET_TX_ID"
  },
  "resourceResult": {
    "target": "algorand.co",
    "result": "reachable"
  }
}
```

## What This Proves

- Hermes/Firefly can create a fresh spending policy commitment.
- x402 resource server returns `402 Payment Required`.
- Firefly approves the exact payment commitment before the agent can spend.
- Payment is made on Algorand TestNet.
- Transaction note commits to `policyHash` and `paymentIntent`; the x402 proof also carries `paymentApprovalHash`.
- `X-Payment` proof is verified against Algorand indexer.
- Resource access is granted only after verification.
