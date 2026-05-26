# Hermes Sign402

Hardware-approved x402 payments for an AI agent on Algorand.

Hermes can buy an x402-protected resource from Telegram, but every live payment must pass through a Firefly hardware approval step. The agent never receives the Algorand private key. The local Sign402 Gateway owns payment execution, checks the Firefly-approved policy, asks Firefly to approve the exact payment hash, sends the Algorand TestNet transaction, and updates the demo dashboard.

## Main Demo Flow

Preferred setup: run the local demo stack:

```bash
cd "/Users/mp/Documents/Berlin Hack"
bash scripts/start-local-demo.sh
```

This starts:

- x402 resource server: `http://127.0.0.1:8090`
- Sign402 Gateway: `http://127.0.0.1:8099`
- dashboard: `http://127.0.0.1:8100`

Expose only the gateway to server-side Hermes:

```bash
cloudflared tunnel --url http://127.0.0.1:8099
```

Give Hermes the resulting `https://...trycloudflare.com` URL as the Sign402 Gateway URL.

If macOS blocks scripts inside `Documents` with `Operation not permitted`, use the manual launch path below. The script is only a convenience wrapper.

## Manual Launch

Check the resource server:

```bash
curl -sS http://127.0.0.1:8090/health
```

If it is not running, start it:

```bash
cd "/Users/mp/Documents/Berlin Hack/demo-resource-server"
python3 -c 'import sys; sys.path.insert(0, "/Users/mp/Documents/Berlin Hack/demo-resource-server"); from x402_demo.server import main; main()'
```

Check Firefly:

```bash
ls /dev/cu.usb*
```

Start the gateway, replacing the Firefly port if it changed:

```bash
cd "/Users/mp/Documents/Berlin Hack/sign402-gateway"

env FIREFLY_PORT=/dev/cu.usbmodem11301 SIGN402_GATEWAY_PORT=8099 \
/opt/homebrew/opt/python@3.14/bin/python3.14 -c 'import sys; sys.path[:0]=["/Users/mp/Documents/Berlin Hack/payment-executor/.venv/lib/python3.14/site-packages","/Users/mp/Documents/Berlin Hack/sign402-gateway","/Users/mp/Documents/Berlin Hack/sign402-bridge","/Users/mp/Documents/Berlin Hack/live-demo","/Users/mp/Documents/Berlin Hack/payment-executor","/Users/mp/Documents/Berlin Hack/demo-resource-server"]; from sign402_gateway.server import main; main()'
```

Verify:

```bash
curl -sS http://127.0.0.1:8099/health
```

Then open the Cloudflare tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8099
```

## Telegram Commands

First approve a policy:

```text
approve sign402 policy
```

Hermes should call:

```text
POST <gateway-url>/approve-policy
```

The gateway sends the policy hash to Firefly using `PAYMENT=<policyHash>`. The user approves on Firefly. The approved policy is stored locally by the gateway.

Then buy the protected resource:

```text
buy x402 probe for algorand.co
```

Hermes should call:

```text
POST <gateway-url>/agent/buy-probe
Content-Type: application/json

{"target":"algorand.co"}
```

The gateway performs the full flow:

```text
request resource -> receive 402 -> check policy -> Firefly payment approval -> Algorand TestNet payment -> retry with X-Payment -> dashboard event
```

## Latest Verified Run

The short-mode Telegram flow was verified end to end:

```text
decision: approved_and_executed
policyHash: c48a9b0b21479ed2ca08dff60c265274f7c5950e7ab4728048f76a5265338490
paymentApprovalHash: 9176849009f5ab571de7eb647f3b718e7ed8c021a991afd9f3ee2c6a3bacea61
txId: HGZ2C5BLWRO6GVQPY3ORYHPAN463FFZWMJMJ5XOI52WQQFHWQR7A
paymentIntent: intent-64dc6816b6438a0f
resource: /probe?target=algorand.co
remainingBudgetAtomic: 950000
result: reachable
```

## Components

- `sign402-gateway`: main orchestration API for Hermes.
- `demo-resource-server`: x402-style protected resource and verifier.
- `payment-executor`: local Algorand TestNet payment sender.
- `demo-dashboard`: live trace for the pitch.
- `sign402-bridge`: older low-level Firefly bridge, kept for debugging.
- `live-demo`: older long-mode local orchestrator, kept for regression/debug runs.

## Safety Notes

- The Algorand private key stays in the local payment executor environment.
- Hermes receives only public metadata such as hashes, tx id, amount, receiver, and resource.
- If Firefly rejects, times out, disconnects, or returns a mismatched hash, the gateway does not send payment.
- The MVP is hardware-approved policy and payment commitments. Firefly-held Algorand signing keys are a post-hackathon milestone.

## Troubleshooting

- `Operation not permitted` from scripts or `.venv` inside `Documents`: grant Terminal/iTerm Full Disk Access, or use the manual launch command above.
- Firefly port errors such as `/dev/cu.usbmodem11301` not found: run `ls /dev/cu.usb*` and restart the gateway with the current port.
- Hermes cannot resolve `*.trycloudflare.com`: run `dig +short <host>.trycloudflare.com` on the Mac and tell Hermes to use `curl --resolve`.
- OpenRouter `HTTP 429` on `openrouter/owl-alpha`: change Hermes to a stable OpenRouter model such as `openai/gpt-4.1-mini`; the key may be fine while the upstream model is rate-limited.

## Verification

```bash
cd "/Users/mp/Documents/Berlin Hack/sign402-gateway"
python3 -m unittest tests/test_gateway_server.py

cd "/Users/mp/Documents/Berlin Hack/demo-resource-server"
python3 -m unittest discover -s tests

cd "/Users/mp/Documents/Berlin Hack"
bash scripts/test_demo_scripts.sh
```
