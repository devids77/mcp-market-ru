#!/usr/bin/env node
/**
 * mcp-market-bridge - stdio <-> Streamable-HTTP proxy for MCP Market Russia.
 *
 * MCP Market Russia is a HOSTED MCP server (https://mcp-market.ru/mcp/), so you
 * do not need this bridge to use it - point your client at that URL directly.
 *
 * The bridge exists for callers that can only launch a local stdio process:
 * MCP catalogs that introspect a server by building its image and speaking
 * `initialize` + `tools/list` over stdio, and clients without remote support.
 * It relays stdio JSON-RPC to the hosted endpoint, so the live tool list is
 * what the caller sees.
 *
 * Zero runtime dependencies - native fetch + node:readline only.
 * The production API image is built from Dockerfile.prod.
 */
const readline = require("node:readline");

const ENDPOINT = process.env.MCP_MARKET_URL || "https://mcp-market.ru/mcp/";
const TIMEOUT_MS = Number(process.env.MCP_MARKET_TIMEOUT_MS || 60000);

let sessionId = null;

/** Extract the JSON-RPC payload from either an SSE stream or a plain JSON body. */
function parseBody(contentType, text) {
  if (!text) return null;
  if ((contentType || "").includes("text/event-stream")) {
    const data = text
      .split(/\r?\n/)
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trim())
      .join("");
    return data ? JSON.parse(data) : null;
  }
  return JSON.parse(text);
}

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

async function forward(msg) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;

  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers,
    body: JSON.stringify(msg),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });

  // The server assigns the session on `initialize`; reuse it for later calls.
  const sid = res.headers.get("mcp-session-id");
  if (sid) sessionId = sid;

  return parseBody(res.headers.get("content-type"), await res.text());
}

const rl = readline.createInterface({ input: process.stdin });

// Messages are handled strictly in order: `initialize` establishes the session
// every later call depends on, so they must not be sent concurrently.
let queue = Promise.resolve();

async function handle(raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    return send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
  }
  const wantsReply = msg.id !== undefined && msg.id !== null;
  try {
    const reply = await forward(msg);
    if (reply && wantsReply) send(reply);
  } catch (err) {
    if (wantsReply) {
      send({ jsonrpc: "2.0", id: msg.id, error: { code: -32603, message: `Bridge error: ${err.message}` } });
    }
  }
}

rl.on("line", (line) => {
  const raw = line.trim();
  if (!raw) return;
  queue = queue.then(() => handle(raw));
});

// Drain in-flight work before exiting, otherwise piped input would terminate
// the process before the replies are written.
rl.on("close", () => {
  queue.then(() => process.exit(0));
});
