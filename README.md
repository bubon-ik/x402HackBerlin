# x402 Hack Berlin

Hackathon prototype for a hardware-approved x402 payment flow.

The project goal is to let an AI agent access paid x402-protected resources while keeping payment approval under explicit user control. The agent can request a purchase, but a local gateway and hardware approval step decide whether a real payment is allowed.

## Planned Architecture

```text
AI agent
  -> Sign402 gateway
  -> hardware approval bridge
  -> payment executor
  -> x402 protected resource
  -> demo dashboard
```

## Repository Layout

```text
sign402-gateway/       Local API gateway for agent payment requests
payment-executor/      Payment execution module
sign402-bridge/        Hardware approval bridge
demo-resource-server/  Local x402-style protected demo resource
live-demo/             Demo runner and scripted flows
demo-dashboard/        Browser dashboard for live events
scripts/               Local development and demo scripts
docs/                  Notes, protocol sketches, and demo docs
```

## Development Status

Current repo state:

- project skeleton is in place;
- `sign402-gateway` has landed as the first core service;
- `sign402-bridge` has landed as the Firefly approval layer;
- the gateway expects the executor, demo resource, and live demo modules to land in follow-up commits.

## Source Of Truth

- [Project spec](docs/project-spec.md)
- [Roadmap](docs/roadmap.md)

## Local Setup

Install and test individual modules from their package directories as they land.

Expected baseline:

```bash
python3 --version
git status
```

Gateway adapter tests:

```bash
PYTHONPATH=sign402-gateway python3 -m unittest sign402-gateway/tests/test_goplausible_adapter.py
```

Bridge tests:

```bash
PYTHONPATH=sign402-bridge python3 -m unittest discover -s sign402-bridge/tests
```

## Demo Flow

The intended demo flow:

1. An agent discovers a paid x402 resource.
2. The local gateway inspects the payment requirement.
3. A human approves the exact payment through hardware.
4. The executor submits the payment.
5. The agent retries the protected request with proof of payment.
6. The dashboard shows the approval and payment result.
