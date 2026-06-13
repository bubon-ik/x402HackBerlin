

Hardware-approved x402 payments for an AI agent on Algorand and Base.

Hermes can buy an official GoPlausible x402-protected API from Telegram, but every live payment must pass through a Firefly hardware approval step. The agent never receives the Algorand private key. The local Sign402 Gateway owns payment execution, checks the Firefly-approved policy, asks Firefly to approve the exact payment hash with a human-readable payment screen, sends the Algorand TestNet USDC transaction through `x402-avm`, and updates the demo dashboard.

The Base Mainnet lane uses CDP API key wallets and the CDP x402 facilitator through `cdp-x402-service`. The same Sign402 rule applies: the gateway checks policy and Firefly must approve the exact payment hash before CDP signs or submits an x402 payment.

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

Then buy the official GoPlausible protected resource:

```text
buy goplausible weather
```

Hermes can now use the paid-tool flow instead of hardcoding the URL:

```text
POST <gateway-url>/agent/inspect-tool
Content-Type: application/json

{"tool":"goplausible.weather"}
```

This returns the tool metadata, x402 payment requirements, receiver, amount, asset, and the Firefly payment approval hash that would be required. If the offer is acceptable, Hermes calls:

```text
POST <gateway-url>/agent/buy-tool
Content-Type: application/json

{"tool":"goplausible.weather"}
```

The gateway performs the full flow:

```text
resolve paid tool -> request GoPlausible weather API -> receive 402 -> check USDC policy -> Firefly payment approval -> x402-avm PAYMENT-SIGNATURE -> GoPlausible facilitator settlement -> protected weather JSON -> dashboard event
```

On payment approval, Firefly receives a `PAYMENT-CONTEXT` pre-command before the hash. For the GoPlausible weather demo the device shows:

```text
x402 WEATHER
0.01 USDC
GoPlausible API
Hash ....<last4>
OK / CANCEL
```

For the Base Mainnet CDP demo, approve a Base USDC policy:

```json
{
  "version": "1",
  "agentId": "hermes-demo",
  "policyId": "policy-base-usdc-001",
  "allowedPurpose": "x402_api_access",
  "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913",
  "maxBudgetAtomic": "100000",
  "maxPerPaymentAtomic": "10000",
  "nonce": "base-mainnet-usdc-001"
}
```

Then Hermes can use the same paid-tool flow from Telegram:

```text
buy base sign402 report
```

Hermes should call:

```text
POST <gateway-url>/agent/inspect-tool
Content-Type: application/json

{"tool":"base.sign402.report"}
```

Then:

```text
POST <gateway-url>/agent/buy-tool
Content-Type: application/json

{"tool":"base.sign402.report"}
```

The gateway performs:

```text
resolve paid tool -> request local Base x402 seller -> receive 402 -> check Base USDC policy -> Firefly payment approval -> CDP Wallet x402 payment -> Coinbase facilitator settlement on Base Mainnet -> protected Sign402 report JSON
```

The built-in Base tool catalog also includes a public X/Twitter profile lookup:

```text
buy x profile elonmusk
```

Hermes should call:

```text
POST <gateway-url>/agent/inspect-tool
Content-Type: application/json

{"tool":"x402.twitter.profile","username":"elonmusk"}
```

Then:

```text
POST <gateway-url>/agent/buy-tool
Content-Type: application/json

{"tool":"x402.twitter.profile","username":"elonmusk"}
```

This resolves to `https://x402.twit.sh/users/by/username?username=elonmusk` and currently costs `0.005 USDC`.

Additional built-in Base USDC paid tools:

```text
buy crypto news
buy hyperliquid BTC
buy funding BTC
buy ens vitalik.eth
buy token price ETH
```

These map to public x402 Bazaar endpoints for Otto AI crypto news, Hyperliquid market data, cross-venue funding rates, OneSource ENS resolution, and Anchor token prices.

For any external Base Mainnet x402 endpoint that charges Base USDC, Hermes can use the raw URL flow:

```text
buy x402 https://merchant.example/paid-resource
```

Hermes should inspect first:

```text
POST <gateway-url>/agent/inspect-x402
Content-Type: application/json

{"url":"https://merchant.example/paid-resource"}
```

This returns a `quoteText` such as:

```text
Base x402 quote: 0.01 USDC on Base Mainnet.
```

Then Hermes executes:

```text
POST <gateway-url>/agent/buy-x402
Content-Type: application/json

{"url":"https://merchant.example/paid-resource"}
```

Raw URL purchases are intentionally limited to Base Mainnet USDC. Other networks or assets are rejected before Firefly approval.

## Official GoPlausible x402 Path

The main hackathon demo uses the official GoPlausible/x402-v2 weather endpoint:

```text
https://x402.goplausible.xyz/examples/weather
```

For protocol inspection without payment:

```text
POST <gateway-url>/agent/inspect-x402
Content-Type: application/json

{"url":"https://example.x402.goplausible.xyz/..."}
```

For raw URL purchases, `/agent/inspect-x402` and `/agent/buy-x402` fetch an external `402 Payment Required` response, normalize the official x402 fields, and accept only Base Mainnet USDC requirements. The response includes a compact `telegramText` receipt with a clickable Basescan transaction link after payment.

For agent-facing paid tools, use:

```text
GET  <gateway-url>/agent/tools
POST <gateway-url>/agent/inspect-tool
POST <gateway-url>/agent/buy-tool
```

The first built-in paid tool is `goplausible.weather`, an MCP-style wrapper around the external GoPlausible x402 weather resource. This makes the demo read as "agent uses a paid tool" while still settling against the official x402 resource.

Current status:

- implemented: official GoPlausible/x402-v2 payment requirement parsing;
- implemented: Sign402 payment hash construction from normalized official requirements;
- implemented: official `x402-avm` `PAYMENT-SIGNATURE` payment group creation for Algorand TestNet USDC;
- implemented: gateway endpoint `POST /agent/buy-x402` for Firefly-approved Base Mainnet USDC raw URL purchases;
- implemented: paid-tool catalog, `POST /agent/inspect-tool`, and `POST /agent/buy-tool` for MCP-style agent flow;
- tested through Hermes Telegram: GoPlausible weather API returned `200 OK` with transaction `BTVGJ3MN42KKFBUN6BV3QRDZZDO54H2OCDX5LKHRU3PFASFYW72A`.

For official GoPlausible payments, use the paid-tool wrapper `goplausible.weather`; raw URL `/agent/buy-x402` is reserved for Base Mainnet USDC endpoints. For Base raw URL payments, approve a policy whose `asset` is `0x833589fCD6eDb6E08f4c7C32D4f71b54bDa02913` and whose budget fields are in USDC atomic units. Then Hermes calls:

```text
POST <gateway-url>/agent/buy-x402
Content-Type: application/json

{"url":"https://merchant.example/paid-resource"}
```

If an external x402 resource does not provide its own nonce or payment intent, the gateway creates a fresh local Sign402 intent for each purchase. This keeps replay protection on while still allowing repeat purchases from resources that return stable payment requirements.

## Latest Verified Run

Official GoPlausible x402-v2 Telegram flow:

```text
command: buy goplausible weather
decision: approved_and_executed
mode: official_x402_avm
asset: USDC TestNet ASA 10458941
amountAtomic: 10000
amount: 0.01 USDC
txId: BTVGJ3MN42KKFBUN6BV3QRDZZDO54H2OCDX5LKHRU3PFASFYW72A
receiver: ZMFK2OI7ZBD2U27ISERZC4S6LKM6WMFJPZQ4MYNJDZ2VNBNMBA67RA22AA
remainingBudgetAtomic: 80000
result: official_x402_resource_access_granted
resource: https://x402.goplausible.xyz/examples/weather
```

The response included protected weather data for New York, London, Tokyo, Sydney, and Dubai after Firefly approval and GoPlausible facilitator settlement.

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
- `sign402-gateway/sign402_gateway/goplausible.py`: GoPlausible/x402-v2 requirement adapter.
- `cdp-x402-service`: CDP Wallet helper for Base Mainnet x402 buyer and seller flows.
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
python3 -m unittest tests/test_goplausible_adapter.py

cd "/Users/mp/Documents/Berlin Hack/demo-resource-server"
python3 -m unittest discover -s tests

cd "/Users/mp/Documents/Berlin Hack"
bash scripts/test_demo_scripts.sh
```
