const assert = require("node:assert/strict");
const test = require("node:test");

test("framed Ollama reasoning markers become fixed safe public progress", async () => {
  const { safeOllamaProgressStatus } = await import("../lib/liveOllamaProgress.mjs");
  const status = safeOllamaProgressStatus(
    "\u001b[95m│ [world plan] reasoning is active; private model thoughts are hidden.\u001b[0m",
  );
  assert.equal(status, "Local Ollama is processing the plan; only safe progress is shown.");
  assert.doesNotMatch(status, /thought|reasoning|chain.of.thought/i);
});

test("framed Ollama answer markers say structured output stays hidden until validation", async () => {
  const { safeOllamaProgressStatus } = await import("../lib/liveOllamaProgress.mjs");
  const status = safeOllamaProgressStatus(
    "│ [world plan] preparing the structured result; raw JSON is hidden.",
  );
  assert.equal(
    status,
    "Local Ollama is preparing its structured plan; raw JSON stays hidden until validation.",
  );
});

test("arbitrary model text, including private reasoning, is never copied into public status", async () => {
  const { safeOllamaProgressStatus } = await import("../lib/liveOllamaProgress.mjs");
  assert.equal(
    safeOllamaProgressStatus("│ [world plan] hidden chain-of-thought: keep this private"),
    "",
  );
  assert.equal(
    safeOllamaProgressStatus("│ [world plan] private model thoughts are hidden."),
    "",
  );
});
