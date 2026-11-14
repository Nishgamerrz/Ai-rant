const assert = require("node:assert/strict");
const test = require("node:test");

test("newline-framed helper output updates progress, tools, and exact public text", async () => {
  const { liveSubagentActivityEvents, parseLiveSubagentLog } = await import(
    "../lib/liveSubagentLog.mjs"
  );
  const resultText = "A complete map result, with its exact line break.\nSecond line.";
  const log = [
    "\u001b[95m[subagent progress] t1 · Map and camera plan started. Public result will stream below.\u001b[0m",
    "\u001b[35m[subagent tool] t1 · search_roblox_meshes started (query=house)\u001b[0m",
    "\u001b[94m[subagent answer] t1 · public result (streaming):\u001b[0m",
    `[subagent answer chunk] t1 · ${JSON.stringify("A complete map result, with its exact line break.\n")}`,
    `[subagent answer chunk] t1 · ${JSON.stringify("Second line.")}`,
    "\u001b[95m[subagent progress] t1 · Map and camera plan complete in 12s; the full public result streamed above.\u001b[0m",
  ].join("\n");

  const calls = parseLiveSubagentLog(log);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].status, "complete");
  assert.equal(calls[0].output, resultText);
  assert.match(calls[0].publicStatus, /complete in 12s/);
  assert.deepEqual(calls[0].toolActivity.map((event) => event.tool), ["search_roblox_meshes"]);
  assert.match(calls[0].toolActivity[0].publicStatus, /query=house/);

  const events = liveSubagentActivityEvents(log);
  assert.ok(events.some((event) => event.type === "subagent_progress"));
  assert.ok(events.some((event) => event.type === "subagent_tool"));
  assert.ok(events.some((event) => event.type === "subagent_answer" && event.text === resultText));
});

test("reused task ids start a fresh live card after the previous task completes", async () => {
  const { parseLiveSubagentLog } = await import("../lib/liveSubagentLog.mjs");
  const log = [
    "[subagent progress] t1 · Map plan started.",
    `[subagent answer chunk] t1 · ${JSON.stringify("first result")}`,
    "[subagent progress] t1 · Map plan complete.",
    "[subagent progress] t1 · Model design started.",
    `[subagent answer chunk] t1 · ${JSON.stringify("second result")}`,
  ].join("\n");
  const calls = parseLiveSubagentLog(log);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map((call) => call.output), ["first result", "second result"]);
  assert.deepEqual(calls.map((call) => call.status), ["complete", "streaming"]);
});
