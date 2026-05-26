# Sign402 - Hardware Consent Layer for Agentic Payments

## One-liner

**Sign402 lets humans safely delegate limited payment authority to AI agents by using Firefly as a hardware consent device for x402 payments.**

## Short Pitch

x402 lets AI agents pay for internet services. But giving an agent direct wallet access is unsafe.

Sign402 adds a hardware consent layer using Firefly, so humans can approve or delegate limited spending policies to agents. The agent can still pay autonomously, but only within a hardware-signed policy.

**Tagline:** Hardware-backed spending limits for autonomous agents.

## Problem

x402 enables AI agents to pay for APIs, services, and digital resources directly over HTTP.

But if agents can pay autonomously, a new problem appears:

**Who controls the agent's wallet and spending permissions?**

Current options are weak:

- give the agent wallet keys, which is dangerous;
- approve every payment manually in a normal wallet, which is annoying;
- rely only on backend limits, which is less trustworthy;
- use API keys or subscriptions, which goes against the x402 pay-per-request model.

Agentic commerce needs a safe way for humans to delegate spending power to agents.

## Solution

**Sign402 turns Firefly into a physical payment consent and policy device.**

Instead of giving an AI agent unlimited wallet access, the user defines or approves a spending policy on Firefly:

```json
{
  "agent": "travel-agent-demo",
  "merchant": "api.example.com",
  "maxAmount": "0.05 USDC",
  "purpose": "network_probe",
  "expiresAt": "2026-06-06T18:00:00Z",
  "nonce": "berlin-demo-001"
}
```

Firefly displays the request and lets the user approve or reject it with physical buttons.

After approval, Firefly signs an authorization message. The agent can then complete the x402 payment flow using Algorand, while attaching the Firefly-signed consent proof.

## Demo Flow

1. AI agent requests access to a paid service:

```http
GET /premium-resource
```

2. Merchant responds with:

```http
402 Payment Required
```

3. Agent prepares a payment request.

4. Firefly displays:

```text
Agent: Travel Agent
Merchant: Berlin API Node
Amount: 0.05 USDC
Purpose: network_probe
Approve?
```

5. User approves on Firefly.

6. Firefly signs the authorization.

7. Agent sends payment through Algorand.

8. Merchant verifies:

- Algorand payment transaction;
- x402 payment proof;
- Firefly-signed authorization;
- nonce, expiration, and amount limit.

9. Merchant grants access.

## Why This Matters

Sign402 solves a real adoption problem for agentic commerce:

**AI agents need spending permissions, but humans need control.**

The project introduces a hardware-backed consent layer between:

- user;
- AI agent;
- merchant;
- payment network.

This makes agent payments safer, auditable, and easier to trust.

## Hackathon Tracks

### x402 Payments

Sign402 is built around the x402 flow:

```text
request -> 402 Payment Required -> payment -> access
```

It adds a missing trust layer before the agent pays.

### Agentic Commerce

The main user is an AI agent buying services autonomously.

Sign402 allows agents to pay without giving them unlimited wallet control.

### Cross-Border Payments

The merchant and user can be in different countries.

Algorand provides fast, low-cost settlement without card networks, bank rails, or regional payment providers.

### Tokenization

The Firefly-signed consent can act like a tokenized spending capability:

```text
This agent may spend up to X for Y purpose until Z time.
```

Later, this can evolve into transferable access passes, prepaid credits, or policy tokens.

### DeFi

Future version: agents could use signed policies to perform limited swaps, route payments, or manage liquidity without full wallet access.

### RWA

Optional extension: the merchant can be a physical device, sensor node, charger, vending machine, or access system.

Firefly controls agent spending for real-world services.

## MVP Scope

For the hackathon, the MVP should be simple:

- mock merchant endpoint with x402-style `402 Payment Required`;
- AI agent/client that attempts to buy access;
- Firefly approval screen;
- Firefly approve/reject buttons;
- signed authorization message;
- Algorand TestNet payment;
- merchant verification;
- dashboard showing the full flow.

## What Firefly Does

Firefly does not need to implement the whole Algorand wallet.

For MVP, Firefly can:

- display payment request details;
- let user approve or reject physically;
- sign an authorization message;
- return signed consent to the agent.

The actual Algorand payment can be executed by the app/server after Firefly approval.

This keeps the project realistic for a 36-hour hackathon.

## Key Technical Idea

Separate **payment execution** from **payment consent**.

```text
Algorand = settlement layer
x402 = payment protocol
Firefly = human consent / policy signing layer
AI agent = autonomous buyer
Merchant = paid service provider
```

## Suggested Demo Service

The merchant service can be simple. It does not need to be the main invention.

Possible paid services:

- premium API endpoint;
- network probe from Berlin;
- paid file conversion;
- paid AI summary;
- paid webhook execution;
- simulated access to a physical or digital resource.

The important part is the payment and consent flow:

```text
agent wants service -> merchant asks for payment -> Firefly approves policy -> Algorand payment -> merchant grants access
```

## Why Judges Might Like It

- It addresses a real weakness in agentic payments.
- It uses Firefly for something meaningful, not decorative.
- It combines hardware, AI agents, x402, and Algorand.
- It is demoable in a few minutes.
- It has a clear path beyond the hackathon.
- It makes autonomous payments feel safer and more practical.

## Main Risk

The main risk is Firefly integration.

Before the hackathon, it is important to verify:

- Firefly can be connected over USB-C;
- custom firmware can be flashed;
- text can be displayed on the screen;
- buttons can be read;
- the device can sign at least an arbitrary message;
- the signed message can be returned to the app.

If this basic flow works before the event, the full project becomes much more realistic.

## Backup Plan

If Algorand transaction signing from Firefly is too hard, do not force it.

Use Firefly only for signed consent:

```text
Firefly signs authorization -> web app executes Algorand payment -> merchant verifies both
```

This is still a strong project because the core idea is hardware consent for agentic payments, not replacing the wallet implementation.

