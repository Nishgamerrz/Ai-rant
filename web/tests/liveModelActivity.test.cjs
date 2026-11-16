const assert = require("node:assert/strict");
const test = require("node:test");

const { parseLiveModelActivity } = require("../lib/liveModelActivity.mjs");

test("parses the model-authored public summary and a wrapped public answer", () => {
  const log = [
    "2026-01-01T00:00:00Z \u001b[90m┌─ [nish-agent r1/6] MODEL REASONING — PUBLIC SUMMARY ─────\u001b[0m",
    "2026-01-01T00:00:01Z \u001b[36m│ I’ll inspect the live parser and add the missing UI panel.\u001b[0m",
    "2026-01-01T00:00:02Z \u001b[90m└───────────────────────────────────────────────────────\u001b[0m",
    "┌─ Ollama activity ─────────────────────────────────────",
    "│ [nish-agent r1/6] answer ▸ I’ll update the chat view and preserve the safe public-output boundary.",
    "│ Then I’ll add regression tests for the live display.",
    "└───────────────────────────────────────────────────────",
  ].join("\n");
  const parsed = parseLiveModelActivity(log);
  assert.equal(parsed.summary, "I’ll inspect the live parser and add the missing UI panel.");
  assert.equal(parsed.summaryKind, "rationale");
  assert.deepEqual(parsed.answers, [{
    label: "nish-agent r1/6",
    text: "I’ll update the chat view and preserve the safe public-output boundary. Then I’ll add regression tests for the live display.",
    streaming: false,
  }]);
});

test("uses only the selected model’s allowlisted public status as the current update", () => {
  const log = [
    "┌─ Ollama activity ─────────────────────────────────────",
    "│ [nish-agent r1/6] public status ▸ I’m inspecting the selected file before changing it.",
    "[agent progress] I’ve confirmed the parser path and am adding its regression test.",
  ].join("\n");
  const parsed = parseLiveModelActivity(log);
  assert.equal(parsed.summary,
    "I’ve confirmed the parser path and am adding its regression test.");
  assert.equal(parsed.summaryKind, "status");
});

test("labels an explicitly streamed public rationale separately from progress status", () => {
  const parsed = parseLiveModelActivity(
    "│ [nish-agent r1/6] public rationale ▸ A short public explanation of the chosen approach.",
  );
  assert.equal(parsed.summary, "A short public explanation of the chosen approach.");
  assert.equal(parsed.summaryKind, "rationale");
});

test("updates a public summary and answer while their framed output is still arriving", () => {
  const log = [
    "┌─ [nish-agent r2/6] MODEL REASONING — PUBLIC SUMMARY ─────",
    "│ I’m checking the stream parser",
    "┌─ Ollama activity ─────────────────────────────────────",
    "│ [nish-agent r2/6] answer ▸ The live answer starts here",
  ].join("\n");
  const parsed = parseLiveModelActivity(log);
  assert.equal(parsed.summary, "I’m checking the stream parser");
  assert.equal(parsed.summaryKind, "rationale");
  assert.deepEqual(parsed.answers, [{
    label: "nish-agent r2/6",
    text: "The live answer starts here",
    streaming: true,
  }]);
});

test("filters hidden-reasoning markers, JSON wrappers, and redacts credentials", () => {
  const unsafe = [
    "[agent progress] My private reasoning is to expose the scratchpad.",
    "[agent progress] {\"public_status\":\"raw JSON\"}",
    "┌─ [nish-agent r3/6] MODEL REASONING — PUBLIC SUMMARY ─────",
    "│ Here's my chain-of-thought; keep it visible.",
    "└───────────────────────────────────────────────────────",
    "┌─ Ollama activity ─────────────────────────────────────",
    "│ [nish-agent r3/6] answer ▸ hidden chain-of-thought text",
    "└───────────────────────────────────────────────────────",
  ].join("\n");
  assert.deepEqual(parseLiveModelActivity(unsafe), { summary: "", summaryKind: "", answers: [] });

  const redacted = parseLiveModelActivity(
    "[agent progress] Inspecting request with Bearer abcdefghijklmnop123456",
  );
  assert.equal(redacted.summary, "Inspecting request with Bearer [REDACTED]");

  const namedSecret = parseLiveModelActivity(
    "[agent progress] BazaarLink is configured with BAZAAR_LINK_API=private-value-123",
  );
  assert.equal(namedSecret.summary,
    "BazaarLink is configured with BAZAAR_LINK_API=[REDACTED]");
});
