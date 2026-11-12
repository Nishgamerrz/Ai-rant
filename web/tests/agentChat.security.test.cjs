const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

const temp = fs.mkdtempSync(path.join(os.tmpdir(), "nishagent-chat-test-"));
const source = fs.readFileSync(path.join(__dirname, "..", "lib", "agentChat.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
}).outputText;
const compiledPath = path.join(temp, "agentChat.cjs");
fs.writeFileSync(compiledPath, compiled);
const { verifyActionsOidcToken } = require(compiledPath);
const { privateKey, publicKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "test-key", alg: "RS256", use: "sig" };
const fetchJwks = async () => ({ ok: true, json: async () => ({ keys: [jwk] }) });

function signedToken(overrides = {}) {
  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: "RS256", kid: "test-key", typ: "JWT" })).toString("base64url");
  const claims = Buffer.from(JSON.stringify({
    iss: "https://token.actions.githubusercontent.com",
    aud: "nishagent-chat",
    exp: now + 300,
    nbf: now - 5,
    iat: now - 5,
    run_id: "123456",
    repository: "Nishgamerrz/Ai-rant",
    event_name: "workflow_dispatch",
    workflow_ref: "Nishgamerrz/Ai-rant/.github/workflows/agent.yml@refs/heads/main",
    ...overrides,
  })).toString("base64url");
  const payload = `${header}.${claims}`;
  return `${payload}.${crypto.sign("RSA-SHA256", Buffer.from(payload), privateKey).toString("base64url")}`;
}

test("accepts a signed Actions token for the exact NishAgent run", async () => {
  const claims = await verifyActionsOidcToken(signedToken(), "123456", fetchJwks);
  assert.equal(claims?.run_id, "123456");
  assert.equal(claims?.repository, "Nishgamerrz/Ai-rant");
});

test("rejects tokens not bound to the right audience, repository, workflow, event, or run", async () => {
  const badClaims = [
    { run_id: "999999" },
    { aud: "other-service" },
    { repository: "attacker/other-repo" },
    { event_name: "push" },
    { workflow_ref: "Nishgamerrz/Ai-rant/.github/workflows/main.yml@refs/heads/main" },
  ];
  for (const override of badClaims) {
    assert.equal(await verifyActionsOidcToken(signedToken(override), "123456", fetchJwks), null,
      `unexpectedly accepted ${JSON.stringify(override)}`);
  }
  assert.equal(await verifyActionsOidcToken(signedToken(), "999999", fetchJwks), null);
});

test("rejects an invalid signature and expired token", async () => {
  const token = signedToken();
  const parts = token.split(".");
  const badSignature = `${parts[0]}.${parts[1]}.${Buffer.alloc(256, 7).toString("base64url")}`;
  assert.equal(await verifyActionsOidcToken(badSignature, "123456", fetchJwks), null);
  assert.equal(await verifyActionsOidcToken(signedToken({ exp: 1 }), "123456", fetchJwks), null);
});

test.after(() => fs.rmSync(temp, { recursive: true, force: true }));
