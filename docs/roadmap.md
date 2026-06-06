# Hermes Sign402 - Roadmap

## Checklist

### Now

- [x] Build Sign402 Gateway on `127.0.0.1:8099`.
- [x] Add gateway endpoint `POST /execute-payment`.
- [x] Test Sign402 Gateway `/health`.
- [x] Test Sign402 Gateway `/approve-payment` against real Firefly.
- [x] Test Sign402 Gateway `/execute-payment` against real Algorand TestNet payment.
- [x] Run one tunnel to the gateway.
- [x] Give Hermes the gateway URL.
- [x] Complete Hermes Telegram strict live flow through gateway.
- [x] Complete Hermes Telegram short-mode `/agent/buy-probe` flow.
- [x] Build first static demo dashboard.
- [x] Add live event endpoint and polling to demo dashboard.
- [x] Make gateway write completed `/agent/buy-probe` runs to `/events/latest`.
- [x] Add one-command local demo launcher.
- [x] Fix resource server to generate fresh `paymentIntent` per 402.
- [x] Add Sign402 Gateway `/agent/buy-probe` orchestration endpoint.
- [x] Update Hermes prompt to use only gateway `/agent/buy-probe`.
- [x] Add GoPlausible/x402-v2 requirement inspection endpoint.
- [x] Add GoPlausible/x402-v2 normalization tests.
- [x] Opt sender account into GoPlausible TestNet USDC ASA `10458941`.
- [x] Fund sender with TestNet USDC.
- [x] Prove official GoPlausible weather x402 payment with `x402-avm`.
- [x] Add gateway endpoint `POST /agent/buy-x402`.
- [x] Prove official GoPlausible weather purchase through Hermes Telegram.
- [x] Rehearse the official GoPlausible paid-tool demo end to end.
- [x] Add city-aware compact Telegram receipts for weather purchases.
- [ ] Polish dashboard for the official paid-tool flow.

### Done

- [x] Choose Firefly as the hardware device for the hackathon MVP.
- [x] Flash Firefly with custom firmware.
- [x] Verify Firefly USB serial communication.
- [x] Validate older Firefly `POLICY=<hash>` approval path.
- [x] Add Firefly `PAYMENT=<hash>` approval.
- [x] Add Firefly approve/cancel button handling.
- [x] Add button debounce.
- [x] Identify Firefly button GPIO mapping.
- [x] Build local Sign402 bridge.
- [x] Add `POST /approve-policy`.
- [x] Add `POST /approve-payment`.
- [x] Build x402 demo resource server.
- [x] Build Algorand TestNet payment executor.
- [x] Fund TestNet sender account.
- [x] Fund TestNet receiver account.
- [x] Prove real Algorand TestNet payment.
- [x] Prove strict local flow: Firefly approval before payment.
- [x] Update project spec.
- [x] Create roadmap.
- [x] Create initial Sign402 Gateway package.
- [x] Add Sign402 Gateway tests.
- [x] Install `pyserial` into the payment executor venv for unified gateway runtime.
- [x] Send real Algorand TestNet payment through Sign402 Gateway.
- [x] Run gateway tunnel:
  `https://avatar-constitutional-deeper-numeric.trycloudflare.com`
- [x] Run resource tunnel:
  `https://eric-occasionally-approx-insert.trycloudflare.com`
  Historical low-level tunnel. The main short-mode demo no longer needs a resource tunnel.
- [x] Complete Hermes Telegram full flow:
  `APPROVED & EXECUTED`
- [x] Confirm resource result:
  `reachable`
- [x] Create static demo dashboard:
  `demo-dashboard/index.html`
- [x] Add gateway event endpoint:
  `GET/POST /events/latest`
- [x] Add dashboard polling against:
  `http://127.0.0.1:8099/events/latest`
- [x] Add local demo launcher:
  `scripts/start-local-demo.sh`
- [x] Fix replay issue by making resource server issue fresh pending payment intents.
- [x] Add short UX endpoint:
  `POST /agent/buy-probe`

### Next

- [x] Integrate Hermes Telegram with gateway.
- [x] Build first static demo dashboard.
- [x] Add live event endpoint and polling to demo dashboard.
- [x] Make gateway write completed runs to `/events/latest`.
- [x] Add one-command local demo launcher.
- [x] Fix resource server fresh intent generation.
- [x] Add Sign402 Gateway `/agent/buy-probe`.
- [x] Update Hermes prompt to use only `/agent/buy-probe`.
- [x] Create hackathon demo script.
- [ ] Create pitch deck.
- [x] Prepare clean hackathon repo plan.
- [x] Publish clean hackathon repo with runnable modules and tests.
- [x] Wire `x402-avm` SDK to create official `PAYMENT-SIGNATURE` payment groups.
- [x] Test against a live GoPlausible protected API/resource.
- [x] Rehearse `/agent/buy-x402` through Hermes Telegram with Firefly approval.
- [x] Rehearse `/agent/buy-tool` through Hermes Telegram with compact city receipt.

### Later / Milestone

- [ ] Move Algorand signing key into Firefly or a secure hardware signer.
- [ ] Sign Algorand transactions on hardware after physical approval.
- [x] Show human-readable payment summary on Firefly.
- [ ] Add independent x402 merchants for non-weather paid tools.
- [ ] Add durable replay protection.
- [ ] Add production-grade gateway auth.
- [ ] Add mainnet mode.

## Current Stage

The project is in **demo-ready MVP / polish phase**.

We have a working official x402 paid-tool demo:

- Firefly is flashed with custom firmware.
- Firefly can approve policy and payment hashes with `PAYMENT=<hash>`.
- The Sign402 Gateway exposes:
  - `POST /approve-policy`
  - `POST /approve-payment`
  - `POST /execute-payment`
  - `POST /agent/buy-probe`
  - `POST /agent/inspect-x402`
  - `POST /agent/buy-x402`
  - `GET /agent/tools`
  - `POST /agent/inspect-tool`
  - `POST /agent/buy-tool`
  - `GET/POST /events/latest`
- The x402 demo resource server returns `402 Payment Required` with a fresh `paymentIntent` for each unpaid request.
- The payment executor sends real Algorand TestNet payments.
- Hermes Telegram has completed live official GoPlausible weather purchases through `/agent/buy-tool`.
- Gateway responses now include compact `telegramText` receipts, e.g.:

```text
✅ Dubai Weather: 86°F, Sunny. Paid 0.01 USDC. Tx WCEOLASN65WVXWVOBAUVAPJHMHRNMLRPN6JIIHCMBPIFE7NDR4UA. Budget left 0.97 USDC.
```

The local `/agent/buy-probe` demo resource remains available as a regression and backup path.

## GoPlausible / Official x402 Status

The project now has a separate compatibility lane for GoPlausible/x402-v2 resources:

- `POST /agent/inspect-x402` fetches an external x402 resource.
- It expects `402 Payment Required`.
- It accepts official Algorand x402 fields:
  - `amount`
  - `payTo`
  - CAIP-2 `network`
  - numeric ASA `asset`
  - `extra`
- It normalizes them into the Sign402 payment commitment shape.
- It returns the `paymentApprovalHash` that Firefly would approve.
- `POST /agent/buy-x402` performs the official GoPlausible purchase path after Firefly approval.
- `GET /agent/tools` exposes a small paid-tool catalog for Hermes.
- `POST /agent/inspect-tool` lets Hermes inspect a paid tool offer before spending.
- `POST /agent/buy-tool` executes the approved paid tool through the same official x402 path.

This proves the project can understand and pay a live official GoPlausible/x402-v2 resource. The implemented official path is:

```text
official 402 -> Firefly approval hash -> x402-avm paymentGroup -> PAYMENT-SIGNATURE -> facilitator settlement -> 200 OK
```

The first paid tools are:

```text
tool: goplausible.weather
MCP-style name: get_weather
resource: https://x402.goplausible.xyz/examples/weather

tool: sign402.qr
MCP-style name: create_qr_code
input: url/text/data/target
artifact: qrImageUrl
```

This makes the main agent experience tool-oriented:

```text
agent lists/inspects paid tool -> sees price/asset/receiver -> Firefly approval -> x402 payment -> tool result
```

Hermes Telegram proof returned weather JSON from GoPlausible with transactions:

```text
BTVGJ3MN42KKFBUN6BV3QRDZZDO54H2OCDX5LKHRU3PFASFYW72A
WB44C5U2Q73AP5XPD55GMTUVBKDUJZTI6LGT4ZOMZQ2VJKFDHDSQ
WCEOLASN65WVXWVOBAUVAPJHMHRNMLRPN6JIIHCMBPIFE7NDR4UA
```

Latest official x402 run:

```text
command: buy weather for Dubai
asset: USDC TestNet ASA 10458941
amount: 10000 atomic / 0.01 USDC
remaining budget: 970000 atomic / 0.97 USDC
city: Dubai
weather: 86°F, Sunny
result: official_x402_resource_access_granted
```

## Product Goal

Hermes Sign402 is a Telegram AI agent that can pay for x402 resources on Algorand, but only when payments fit a Firefly-approved policy and only after physical Firefly approval for the exact payment commitment.

## What Works Now

### Hardware

- Firefly connects over USB serial.
- Firefly displays human payment context plus the short approval hash on screen.
- Firefly approve/cancel buttons work.
- Current button mapping:
  - `GPIO10`: approve
  - `GPIO8`: cancel
  - `GPIO3` and `GPIO2`: spare buttons

### Local Services

- `sign402-bridge` works on `127.0.0.1:8088`.
- `sign402-gateway` works on `127.0.0.1:8099`.
- `demo-resource-server` works on `127.0.0.1:8090`.
- `payment-executor` can send Algorand TestNet payments.
- `live-demo` can orchestrate strict Firefly approval before payment.
- Hermes can call the gateway tunnel for Firefly approval and payment execution.

### Security Properties In MVP

- Hermes should not receive private keys.
- Firefly must approve policy creation.
- Firefly can approve/reject individual payment commitments.
- Firefly shows the exact payment context before approval, e.g. `x402 WEATHER`, `0.01 USDC`, `GoPlausible API`, and the short hash.
- If Firefly rejects, times out, disconnects, or hash mismatches, payment must not be sent.
- Algorand transaction note links payment to `policyHash` and `paymentIntent`.

Current limitation: Firefly approval is hash approval, not Algorand transaction signing. The local payment executor still holds the signing key in the MVP. The production path is hardware-side transaction signing so a compromised gateway cannot execute payment without a physical device signature.

## Current Demo Shape

The current pitch demo uses the official GoPlausible weather x402 path. Server-side Hermes only needs the gateway tunnel:

1. Local demo launcher for resource server, Sign402 Gateway, and dashboard.
2. Tunnel to Sign402 Gateway.
3. Policy approval for USDC TestNet ASA `10458941`.
4. Telegram command `buy weather for <city>`.
5. Gateway endpoint `POST /agent/buy-tool` with `{"tool":"goplausible.weather","city":"<city>"}`.
6. Hermes replies with the gateway `telegramText` field only.

The local demo resource server remains available for regression and backup demos, but it is no longer the main pitch path.

## Next Step

Polish the **official GoPlausible paid-tool dashboard** after the core pitch flow is stable.

The gateway now writes `GET/POST /events/latest`, and the dashboard polls it. The main demo path is:

```text
Telegram command -> gateway /agent/buy-tool -> GoPlausible 402 -> USDC policy check -> Firefly payment approval -> x402-avm PAYMENT-SIGNATURE -> GoPlausible facilitator settlement -> protected weather JSON -> compact Telegram receipt -> gateway event -> dashboard updates
```

## Sign402 Gateway

Sign402 Gateway is one local Mac service that combines the important local capabilities:

- Firefly policy approval.
- Firefly payment approval.
- Algorand payment execution.
- Health/status endpoints.

Proposed local URL:

```text
http://127.0.0.1:8099
```

Proposed endpoints:

```text
GET  /health
POST /approve-policy
POST /approve-payment
POST /execute-payment
GET  /events/latest
POST /events/latest
POST /agent/buy-probe
```

Then only one tunnel is needed for Firefly + payment execution:

```bash
cloudflared tunnel --url http://127.0.0.1:8099
```

Hermes gets one gateway URL and never sees private keys.

## Roadmap

### Phase 1 - Core Proof: Done

- [x] Flash Firefly.
- [x] Verify serial communication.
- [x] Add `PAYMENT=<hash>` approval path.
- [x] Use `PAYMENT=<policyHash>` for policy approval in the gateway.
- [x] Add approve/cancel buttons.
- [x] Build local bridge.
- [x] Build x402 demo server.
- [x] Build Algorand TestNet payment executor.
- [x] Prove strict end-to-end flow locally.

Status: **Done**

### Phase 2 - Gateway: Done

Goal: reduce local demo complexity.

Tasks:

- [x] Create `sign402-gateway`.
- [x] Move or wrap existing bridge endpoints into gateway.
- [x] Add `POST /execute-payment`.
- [x] Reuse existing `payment-executor/.env` locally.
- [x] Return only safe payment data:
  - `txId`
  - `receiver`
  - `amountAtomic`
  - `asset`
  - `paymentIntent`
  - `policyHash`
  - `note`
- [x] Add tests.
- [x] Run one tunnel to gateway.

Status: **Done**

Gateway execution test:

```text
txId: X2F2NHPEVKOHTH3FVIMAJOMCF27C6L5HAL4L5FBH44RSTAIZVO3A
amountAtomic: 50000
asset: ALGO_TEST
paymentIntent: intent-gateway-exec-001
```

Hermes Telegram execution test:

```text
decision: APPROVED & EXECUTED
txId: 6L4YPSZOCK74CPZ3H5GRD4JDMYL2BFVOVTUVIE2HJ34HEYKLEYKQ
paymentApprovalHash: fb44b917f859229622903d48baa7cb398207c1b6ab8a973f7b8048806a7deec9
policyHash: ae33d87d9ac440117de46766714fff110be50e880e22ecf2056aaafb7df147ac
resource: /probe?target=algorand.co
result: reachable
```

### Phase 3 - Hermes Telegram Integration: Done

Goal: make the main demo happen from Telegram.

Tasks:

- [x] Give Hermes:
  - gateway URL
- [x] Main short-mode command:

```text
buy x402 probe for algorand.co
```

- [x] Hermes flow:
  - call gateway `/agent/buy-probe` with `{"target":"algorand.co"}`
  - wait while the gateway checks policy, asks Firefly, pays Algorand, retries the resource, and writes the dashboard event
  - answer in Telegram with decision, tx/result, hashes, and remaining budget
- [x] Keep `/approve-payment` and `/execute-payment` available as low-level debug endpoints.

Status: **Done**

### Phase 4 - Demo Dashboard: Done

Goal: make the pitch visually strong.

Dashboard should show:

- [x] Telegram command.
- [x] Policy hash.
- [x] Firefly device identity.
- [x] Payment requirements.
- [x] Payment approval hash.
- [x] Firefly approve/cancel result.
- [x] Algorand tx id.
- [x] X-Payment retry.
- [x] Final resource access.
- [x] Load latest run dynamically from a JSON/event endpoint.
- [x] Gateway writes the final event after every successful `/agent/buy-probe` run.

Status: **Done**

### Phase 5 - Hackathon Packaging

Goal: make it look like a complete new project.

Tasks:

- [ ] Create fresh hackathon repo at event start.
- [ ] Rewrite clean version from this prototype.
- [ ] Add README.
- [ ] Add architecture diagram.
- [x] Add demo script.
- [ ] Add pitch deck.
- [ ] Add milestone plan.

Status: **Demo packaging in progress**

### Phase 6 - Post-Hackathon Milestone

Goal: turn Firefly from consent device into true signing device.

Tasks:

- [ ] Store Algorand signing key on Firefly.
- [x] Show human-readable payment summary on Firefly.
- [ ] Sign Algorand transactions on Firefly.
- [ ] Broadcast signed transactions from host.
- [ ] Remove private key from Mac executor.

Status: **Milestone / stretch**

## Recommended Immediate Action

Rehearse the hackathon demo script and then create the pitch deck.

This gives us the biggest practical improvement now:

- judges can see the full flow without reading terminal output;
- the dashboard becomes the main pitch surface;
- the short-mode Telegram command feels like a product, not a developer script;
- Firefly remains visibly mandatory for live payments.
