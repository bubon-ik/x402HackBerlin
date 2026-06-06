# Security Model

Hermes Sign402 is a hackathon MVP for hardware-approved x402 payments. It is designed to demonstrate a safer agentic commerce pattern, not to claim production-grade custody.

## What The MVP Enforces

- Hermes never receives the Algorand private key.
- Firefly must physically approve the deterministic policy hash before the agent can spend.
- Firefly must physically approve the exact payment commitment hash before the gateway sends payment.
- The gateway checks asset, purpose, amount, budget, and replayed payment intents before execution.
- Receipts include the paid tool, amount, remaining budget, and a clickable Algorand TestNet transaction link.

## Known Limitations

### Firefly Approval Is Hash Approval, Not Transaction Signing

In the current MVP, Firefly is a hardware consent gate. It displays a human-readable payment context plus the short approval hash, then returns an approval event for that hash.

Firefly does not yet hold the Algorand signing key and does not sign the final Algorand transaction. The signing key remains in the local payment executor on the Mac. If the local gateway or payment executor were compromised, production custody guarantees would require stronger protection than the current MVP provides.

This is intentional for the hackathon scope and is documented as the next security milestone.

Production path:

- move the Algorand signing key into Firefly or another secure hardware signer;
- display full transaction details on device;
- sign the Algorand transaction only after physical approval;
- make the gateway unable to execute any payment without a hardware signature.

### QR Tool Uses A Demo Settlement Rail

`sign402.qr` generates a QR artifact in the gateway after a real x402 payment succeeds. For the hackathon demo, it reuses the live GoPlausible x402 payment resource as the settlement rail so the demo can prove real USDC x402 payment on Algorand with Firefly approval.

That means the QR demo settles through the same live GoPlausible merchant path as the weather demo. In production, each paid tool should expose its own x402 resource URL, merchant receiver, and price metadata.

Production path:

- deploy an independent QR x402 resource;
- give it its own merchant receiver and pricing policy;
- keep the same Firefly approval and receipt UX;
- add multiple independent merchants to the agent discovery manifest.

## Threat Model Summary

The MVP protects against an AI agent receiving unrestricted wallet access. It does not yet fully protect against a compromised local gateway or compromised local payment executor.

The production version should turn Firefly from a hardware approval device into a hardware signing device.

