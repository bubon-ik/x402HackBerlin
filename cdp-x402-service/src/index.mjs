import dotenv from "dotenv";
import express from "express";
import { CdpClient } from "@coinbase/cdp-sdk";
import { facilitator } from "@coinbase/x402";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/client";
import { ExactEvmScheme as ExactEvmServerScheme } from "@x402/evm/exact/server";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import {
  decodePaymentResponseHeader,
  wrapFetchWithPaymentFromConfig,
} from "@x402/fetch";

dotenv.config();

const BASE_MAINNET_CAIP2 = "eip155:8453";
const DEFAULT_ACCOUNT_NAME = "sign402-mainnet-buyer";

async function main() {
  const [command, ...args] = process.argv.slice(2);
  const options = parseArgs(args);

  if (command === "account") {
    const account = await getCdpAccount();
    writeJson({ ok: true, address: account.address, accountName: accountName() });
    return;
  }

  if (command === "buy") {
    const url = requiredOption(options, "url");
    const result = await buyPaidResource(url);
    writeJson(result);
    return;
  }

  if (command === "serve-seller") {
    await serveSeller();
    return;
  }

  throw new Error(`Unknown command: ${command || "<empty>"}`);
}

async function getCdpAccount() {
  assertEnv("CDP_API_KEY_ID");
  assertEnv("CDP_API_KEY_SECRET");
  assertEnv("CDP_WALLET_SECRET");

  const cdp = new CdpClient();
  const name = accountName();
  const account = await cdp.evm.getOrCreateAccount({ name });
  const expectedAddress = process.env.CDP_EVM_ACCOUNT_ADDRESS;

  if (expectedAddress && account.address.toLowerCase() !== expectedAddress.toLowerCase()) {
    throw new Error(
      `CDP account ${name} resolved to ${account.address}, expected ${expectedAddress}`,
    );
  }

  return account;
}

async function buyPaidResource(url) {
  const cdpAccount = await getCdpAccount();
  const fetchWithPayment = wrapFetchWithPaymentFromConfig(fetch, {
    schemes: [
      {
        network: BASE_MAINNET_CAIP2,
        client: new ExactEvmScheme(cdpAccount),
      },
    ],
  });

  const response = await fetchWithPayment(url, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  const bodyText = await response.text();
  const paymentResponse = paymentSettleResponse(response);

  return {
    ok: response.ok,
    status: response.status,
    resourceUrl: url,
    payer: cdpAccount.address,
    body: parseMaybeJson(bodyText),
    paymentResponse,
    transactionHash:
      paymentResponse?.transaction ||
      paymentResponse?.transactionHash ||
      paymentResponse?.txHash ||
      null,
  };
}

async function serveSeller() {
  const payTo = requiredEnv("CDP_SELLER_PAY_TO");
  const port = Number(process.env.CDP_X402_SELLER_PORT || "4021");
  const price = process.env.CDP_X402_SELLER_PRICE || "$0.01";
  const route = process.env.CDP_X402_SELLER_ROUTE || "/paid/sign402-report";
  const app = express();

  const facilitatorClient = new HTTPFacilitatorClient(facilitator);
  const server = new x402ResourceServer(facilitatorClient).register(
    BASE_MAINNET_CAIP2,
    new ExactEvmServerScheme(),
  );

  app.use(
    paymentMiddleware(
      {
        [`GET ${route}`]: {
          accepts: [
            {
              scheme: "exact",
              price,
              network: BASE_MAINNET_CAIP2,
              payTo,
            },
          ],
          description: "Sign402 paid report",
          mimeType: "application/json",
        },
      },
      server,
    ),
  );

  app.get(route, (_req, res) => {
    res.json({
      ok: true,
      product: "sign402-report",
      network: BASE_MAINNET_CAIP2,
      paidAt: new Date().toISOString(),
      report: {
        summary: "This JSON was unlocked by an x402 payment on Base Mainnet.",
      },
    });
  });

  app.get("/health", (_req, res) => {
    res.json({
      ok: true,
      service: "sign402-cdp-x402-seller",
      network: BASE_MAINNET_CAIP2,
      route,
      price,
      payTo,
    });
  });

  app.listen(port, "127.0.0.1", () => {
    console.error(`CDP x402 seller listening on http://127.0.0.1:${port}${route}`);
  });
}

function paymentSettleResponse(response) {
  const header = response.headers.get("PAYMENT-RESPONSE");
  if (!header) return null;
  return decodePaymentResponseHeader(header);
}

function parseMaybeJson(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_error) {
    return text;
  }
}

function accountName() {
  return process.env.CDP_EVM_ACCOUNT_NAME || DEFAULT_ACCOUNT_NAME;
}

function parseArgs(args) {
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const current = args[index];
    if (!current.startsWith("--")) continue;
    const key = current.slice(2);
    const value = args[index + 1];
    if (!value || value.startsWith("--")) {
      options[key] = "true";
      continue;
    }
    options[key] = value;
    index += 1;
  }
  return options;
}

function requiredOption(options, key) {
  const value = options[key];
  if (!value) throw new Error(`--${key} is required`);
  return value;
}

function assertEnv(key) {
  if (!process.env[key]) throw new Error(`${key} is required`);
}

function requiredEnv(key) {
  const value = process.env[key];
  if (!value) throw new Error(`${key} is required`);
  return value;
}

function writeJson(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exitCode = 1;
});
