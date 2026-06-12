# Sign402 CDP x402 Service

CDP Wallet helper for Base Mainnet x402 payments.

The Python Sign402 Gateway still owns policy checks, Firefly approval, and budget state. This service only does the CDP/x402 work after the gateway has approved a payment.

## Setup

```bash
cd "/Users/mp/Documents/Berlin Hack/cdp-x402-service"
npm install
cp .env.example .env
```

Fill `.env` locally. Do not paste secrets into chat or commit them.

Required CDP credentials:

```env
CDP_API_KEY_ID=...
CDP_API_KEY_SECRET=...
CDP_WALLET_SECRET=...
CDP_EVM_ACCOUNT_NAME=sign402-mainnet-buyer
```

Optional but recommended:

```env
CDP_EVM_ACCOUNT_ADDRESS=0x...
```

If this guard is set, the service refuses to spend from any other CDP account.

## Create Or Resolve The Buyer Wallet

```bash
npm run account
```

This creates or reuses the named CDP EVM account and prints its address.

Fund that address on **Base Mainnet** with real USDC before live purchases.

## Buyer Flow

The gateway calls this internally after Firefly approval:

```bash
npm run buy -- --url https://example.com/paid-x402-resource
```

The command writes JSON to stdout:

```json
{
  "ok": true,
  "status": 200,
  "payer": "0x...",
  "transactionHash": "0x..."
}
```

## Seller Flow

To expose a local paid API on Base Mainnet:

```bash
CDP_SELLER_PAY_TO=0xYourReceiverAddress npm run serve
```

Default protected route:

```text
GET http://127.0.0.1:4021/paid/sign402-report
```

Without payment it returns HTTP `402`. With a valid x402 `PAYMENT-SIGNATURE`, the CDP facilitator settles USDC on Base Mainnet and the route returns JSON.

## Mainnet Safety

This service is intentionally Base Mainnet only:

```text
eip155:8453
```

Start with a tiny price such as `$0.001` or `$0.01`, verify the receiver address, and confirm settlement on BaseScan before increasing limits.
