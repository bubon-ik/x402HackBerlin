# GoPlausible x402 Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe GoPlausible/x402-avm compatibility lane without breaking the existing Firefly-approved demo flow.

**Architecture:** Keep `/agent/buy-probe` unchanged. Add a focused adapter that can parse official x402 v2 Algorand `402 Payment Required` payloads, normalize them into the Sign402 commitment shape, and expose a gateway inspection endpoint for Hermes/demo checks. Real official `paymentGroup` settlement remains a separate follow-up because it requires `x402-avm` signer integration.

**Tech Stack:** Python stdlib HTTP server, existing Sign402 Gateway, `unittest`, GoPlausible/x402 Algorand v2 schema.

---

### Task 1: x402 v2 Normalization

**Files:**
- Create: `sign402-gateway/sign402_gateway/goplausible.py`
- Test: `sign402-gateway/tests/test_goplausible_adapter.py`

- [x] **Step 1: Write tests for official GoPlausible/Algorand fields**

Test that `amount`, `payTo`, CAIP-2 `network`, numeric ASA `asset`, and `extra` become a Sign402-compatible normalized object.

- [x] **Step 2: Implement adapter**

Implement `normalize_x402_payment_required(payload, resource_url)` and preserve `originalPaymentRequirements` for auditability.

### Task 2: Gateway Inspect Endpoint

**Files:**
- Modify: `sign402-gateway/sign402_gateway/server.py`
- Test: `sign402-gateway/tests/test_gateway_server.py`

- [x] **Step 1: Add endpoint test**

`POST /agent/inspect-x402` should fetch an external x402 URL through an injected fetcher, return normalized requirements, and build the exact Firefly `paymentApprovalHash` commitment.

- [x] **Step 2: Wire endpoint**

Add the route to health output and handler dispatch. This endpoint must not send payment or require Firefly yet; it is a protocol compatibility checkpoint.

### Task 3: Documentation

**Files:**
- Modify: `README.md`
- Modify: `Hermes Sign402 - Project Spec.md`
- Modify: `Hermes Sign402 - Roadmap.md`

- [x] **Step 1: Document honest status**

Current demo remains working. New GoPlausible lane can inspect/normalize official x402 v2 payment requirements. Full official `X-PAYMENT paymentGroup` execution is next.

### Task 4: Verification

**Commands:**
- `python3 -m unittest sign402-gateway/tests/test_goplausible_adapter.py`
- `python3 -m unittest sign402-gateway/tests/test_gateway_server.py`
- `python3 -m unittest discover -s sign402-gateway/tests`

Expected: all tests pass.
