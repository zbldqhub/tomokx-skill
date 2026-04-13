#!/usr/bin/env node
/**
 * Auto-patch OKX Trade CLI to disable TLS cert verification on ProxyAgent.
 * Required when proxy uses self-signed certs (common with Clash/V2Ray).
 * Run this before using okx CLI through a local HTTP proxy.
 */

const fs = require("fs");
const path = require("path");

const OKX_DIST = path.join(
  process.env.APPDATA || process.env.HOME,
  process.platform === "win32"
    ? "npm/node_modules/@okx_ai/okx-trade-cli/dist/index.js"
    : ".npm-global/lib/node_modules/@okx_ai/okx-trade-cli/dist/index.js"
);

function patch() {
  if (!fs.existsSync(OKX_DIST)) {
    console.error("[patch-okx-cli] ERROR: Cannot find okx-trade-cli dist file at", OKX_DIST);
    process.exit(1);
  }

  let content = fs.readFileSync(OKX_DIST, "utf-8");

  const oldLine = 'this.dispatcher = new ProxyAgent(config.proxyUrl);';
  const newLine = 'this.dispatcher = new ProxyAgent(config.proxyUrl, { requestTls: { rejectUnauthorized: false } });';

  if (content.includes(newLine)) {
    console.log("[patch-okx-cli] Already patched.");
    process.exit(0);
  }

  if (!content.includes(oldLine)) {
    console.error("[patch-okx-cli] ERROR: Expected code pattern not found. The CLI may have been updated.");
    process.exit(1);
  }

  content = content.replace(oldLine, newLine);
  fs.writeFileSync(OKX_DIST, content, "utf-8");
  console.log("[patch-okx-cli] Patched successfully:", OKX_DIST);
}

patch();
