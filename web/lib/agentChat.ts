import { createCipheriv, createDecipheriv, createHash, createPublicKey, randomBytes, timingSafeEqual, verify as verifySignature } from "node:crypto";

const REPO = "Nishgamerrz/Ai-rant";
const API = "https://api.github.com";
const MAX_VARIABLE_BYTES = 46_000;
const ACTIONS_OIDC_ISSUER = "https://token.actions.githubusercontent.com";
const ACTIONS_OIDC_AUDIENCE = "nishagent-chat";
export const MAX_CHAT_MESSAGE_CHARS = 4_000;
export const MAX_CHAT_IMAGE_BYTES = 24_000;
export const MAX_QUEUED_CHAT_MESSAGES = 16;

export type QueueMessage = {
  id: string;
  clientId?: string;
  message: string;
  createdAt: string;
  imageData?: string;
  mimeType?: string;
  fileName?: string;
};

type EncryptedQueue = { v: 1; iv: string; tag: string; data: string };
type RepoVariable = { name: string; value?: string };
type ActionsJwk = { kty: string; kid: string; use?: string; alg?: string; n: string; e: string };
type ActionsOidcClaims = Record<string, any>;

let actionsJwksCache: { expiresAt: number; keys: ActionsJwk[] } | null = null;

async function actionsJwks(fetcher: typeof fetch = fetch): Promise<ActionsJwk[]> {
  if (fetcher === fetch && actionsJwksCache && actionsJwksCache.expiresAt > Date.now()) {
    return actionsJwksCache.keys;
  }
  const response = await fetcher(`${ACTIONS_OIDC_ISSUER}/.well-known/jwks`, { cache: "no-store" });
  if (!response.ok) throw new Error(`GitHub Actions signing-key lookup failed (${response.status})`);
  const payload = await response.json();
  const keys = Array.isArray(payload?.keys) ? payload.keys.filter((key: any) =>
    key?.kty === "RSA" && typeof key?.kid === "string" && typeof key?.n === "string" && typeof key?.e === "string"
    && (!key.use || key.use === "sig") && (!key.alg || key.alg === "RS256")) as ActionsJwk[] : [];
  if (!keys.length) throw new Error("GitHub Actions returned no usable signing keys");
  if (fetcher === fetch) actionsJwksCache = { keys, expiresAt: Date.now() + 15 * 60_000 };
  return keys;
}

/** Validate the short-lived OIDC proof minted inside the matching workflow run. */
export async function verifyActionsOidcToken(token: string, runId: string, fetcher: typeof fetch = fetch): Promise<ActionsOidcClaims | null> {
  const pieces = String(token || "").split(".");
  if (pieces.length !== 3 || pieces.some((piece) => !/^[A-Za-z0-9_-]+$/.test(piece))) return null;
  let header: any;
  let claims: ActionsOidcClaims;
  try {
    header = JSON.parse(Buffer.from(pieces[0], "base64url").toString("utf8"));
    claims = JSON.parse(Buffer.from(pieces[1], "base64url").toString("utf8"));
  } catch {
    return null;
  }
  if (header?.alg !== "RS256" || typeof header?.kid !== "string") return null;
  const jwk = (await actionsJwks(fetcher)).find((key) => key.kid === header.kid);
  if (!jwk) return null;
  try {
    const publicKey = createPublicKey({ key: jwk as any, format: "jwk" });
    const signature = Buffer.from(pieces[2], "base64url");
    const signed = Buffer.from(`${pieces[0]}.${pieces[1]}`, "ascii");
    if (!verifySignature("RSA-SHA256", signed, publicKey, signature)) return null;
  } catch {
    return null;
  }

  const now = Math.floor(Date.now() / 1000);
  const audience = claims.aud;
  const hasAudience = audience === ACTIONS_OIDC_AUDIENCE
    || (Array.isArray(audience) && audience.includes(ACTIONS_OIDC_AUDIENCE));
  const workflowRefs = [claims.workflow_ref, claims.job_workflow_ref].filter((value) => typeof value === "string");
  const isAgentWorkflow = workflowRefs.some((value: string) =>
    value.toLowerCase().startsWith(`${REPO.toLowerCase()}/.github/workflows/agent.yml@`));
  if (claims.iss !== ACTIONS_OIDC_ISSUER || !hasAudience
      || String(claims.run_id || "") !== cleanRunId(runId)
      || String(claims.repository || "").toLowerCase() !== REPO.toLowerCase()
      || claims.event_name !== "workflow_dispatch" || !isAgentWorkflow
      || !Number.isFinite(Number(claims.exp)) || Number(claims.exp) < now - 30
      || (claims.nbf != null && Number(claims.nbf) > now + 30)
      || (claims.iat != null && Number(claims.iat) > now + 30)) return null;
  return claims;
}

function githubToken() {
  const value = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!value) throw new Error("GITHUB_TOKEN missing");
  return value;
}

function githubHeaders() {
  return {
    Authorization: `Bearer ${githubToken()}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
  };
}

function cleanRunId(runId: string) {
  if (!/^\d{1,20}$/.test(String(runId || ""))) throw new Error("invalid run id");
  return String(runId);
}

export function chatAuthVariableName(runId: string) {
  return `NISH_AGENT_AUTH_${cleanRunId(runId)}`;
}

function chatMessagePrefix(runId: string) {
  return `NISH_AGENT_MSG_${cleanRunId(runId)}_`;
}

export function makeChatToken() {
  return randomBytes(32).toString("base64url");
}

export function makeDispatchId() {
  return randomBytes(12).toString("hex");
}

function keyBytes(token: string) {
  if (!/^[A-Za-z0-9_-]{40,64}$/.test(token)) throw new Error("invalid chat session token");
  const key = Buffer.from(token, "base64url");
  if (key.length !== 32) throw new Error("invalid chat session token");
  return key;
}

export function chatTokenHash(token: string) {
  return createHash("sha256").update(keyBytes(token)).digest("hex");
}

export function chatTokenMatches(token: string, expectedHash: string) {
  try {
    const actual = Buffer.from(chatTokenHash(token), "hex");
    const expected = Buffer.from(expectedHash, "hex");
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}

function encryptQueue(messages: QueueMessage[], token: string) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", keyBytes(token), iv);
  const plaintext = Buffer.from(JSON.stringify({ v: 1, messages }), "utf8");
  const encrypted = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const value = JSON.stringify({
    v: 1,
    iv: iv.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
    data: encrypted.toString("base64"),
  } satisfies EncryptedQueue);
  if (Buffer.byteLength(value, "utf8") > MAX_VARIABLE_BYTES) {
    throw new Error("image or message is too large for the encrypted GitHub queue");
  }
  return value;
}

function decryptQueue(value: string, token: string): QueueMessage[] {
  if (!value || Buffer.byteLength(value, "utf8") > MAX_VARIABLE_BYTES) throw new Error("invalid or oversized chat queue");
  const encrypted = JSON.parse(value) as EncryptedQueue;
  if (encrypted.v !== 1 || !encrypted.iv || !encrypted.tag || !encrypted.data) throw new Error("invalid chat queue payload");
  const decipher = createDecipheriv("aes-256-gcm", keyBytes(token), Buffer.from(encrypted.iv, "base64"));
  decipher.setAuthTag(Buffer.from(encrypted.tag, "base64"));
  const clear = Buffer.concat([
    decipher.update(Buffer.from(encrypted.data, "base64")),
    decipher.final(),
  ]).toString("utf8");
  const parsed = JSON.parse(clear);
  if (parsed?.v !== 1 || !Array.isArray(parsed.messages)) throw new Error("invalid chat queue contents");
  return parsed.messages.filter((item: any) =>
    item && typeof item.id === "string" && typeof item.message === "string" && typeof item.createdAt === "string");
}

function variableEndpoint(name: string) {
  return `${API}/repos/${REPO}/actions/variables/${encodeURIComponent(name)}`;
}

export async function readChatVariable(name: string): Promise<string | null> {
  const response = await fetch(variableEndpoint(name), { headers: githubHeaders(), cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`GitHub Actions variable read failed (${response.status})`);
  const value = await response.json();
  if (typeof value?.value !== "string") throw new Error("GitHub returned an invalid Actions variable");
  return value.value;
}

async function createChatVariable(name: string, value: string) {
  const response = await fetch(`${API}/repos/${REPO}/actions/variables`, {
    method: "POST", headers: githubHeaders(), body: JSON.stringify({ name, value }),
  });
  if (response.ok) return;
  throw new Error(`GitHub Actions variable create failed (${response.status})`);
}

export async function deleteChatVariable(name: string) {
  const response = await fetch(variableEndpoint(name), {
    method: "DELETE", headers: githubHeaders(), cache: "no-store",
  });
  if (response.status === 404 || response.status === 204) return;
  if (!response.ok) throw new Error(`GitHub Actions variable delete failed (${response.status})`);
}

async function listChatVariables(prefix: string): Promise<RepoVariable[]> {
  const variables: RepoVariable[] = [];
  const headers = githubHeaders();
  const pageSize = 100;
  for (let page = 1; page <= 5; page++) {
    const response = await fetch(`${API}/repos/${REPO}/actions/variables?per_page=${pageSize}&page=${page}`, {
      headers, cache: "no-store",
    });
    if (!response.ok) throw new Error(`GitHub Actions variable list failed (${response.status})`);
    const payload = await response.json();
    const batch = Array.isArray(payload?.variables) ? payload.variables as RepoVariable[] : [];
    variables.push(...batch.filter((variable) => String(variable.name || "").startsWith(prefix)));
    if (batch.length < pageSize || page * pageSize >= Number(payload?.total_count || 0)) break;
  }
  return variables;
}

export async function getAgentRun(runId: string) {
  const id = cleanRunId(runId);
  const response = await fetch(`${API}/repos/${REPO}/actions/runs/${id}`, {
    headers: githubHeaders(), cache: "no-store",
  });
  if (!response.ok) throw new Error(`GitHub run lookup failed (${response.status})`);
  const run = await response.json();
  const workflowPath = String(run.path || "");
  if (!/(^|\/)agent\.yml(?:@|$)/i.test(workflowPath)) {
    throw new Error("this run does not belong to the NishAgent chat workflow");
  }
  if (run.status !== "in_progress" && run.status !== "queued") {
    throw new Error("this agent run is no longer active");
  }
  return run;
}

export async function registerChatSession(runId: string, token: string) {
  const name = chatAuthVariableName(runId);
  const expected = chatTokenHash(token);
  const current = await readChatVariable(name);
  if (current !== null) {
    if (!chatTokenMatches(token, current)) throw new Error("chat session is already registered");
    return;
  }
  try {
    await createChatVariable(name, expected);
  } catch (error) {
    // A duplicate registration with the same run key is safe; never overwrite a
    // key that was already registered by another browser session.
    const afterRace = await readChatVariable(name);
    if (afterRace === null || !chatTokenMatches(token, afterRace)) throw error;
  }
}

export async function authenticateChatSession(runId: string, token: string) {
  const stored = await readChatVariable(chatAuthVariableName(runId));
  return stored !== null && chatTokenMatches(token, stored);
}

export async function readQueuedMessages(runId: string, token: string, after = "") {
  const prefix = chatMessagePrefix(runId);
  const variables = await listChatVariables(prefix);
  const result: QueueMessage[] = [];
  for (const variable of variables) {
    const id = variable.name.slice(prefix.length);
    if (!id || (after && id <= after)) continue;
    let value = variable.value;
    if (typeof value !== "string") value = await readChatVariable(variable.name) || "";
    if (!value) continue;
    result.push(...decryptQueue(value, token));
  }
  return result.sort((a, b) => a.id.localeCompare(b.id));
}

export async function acknowledgeQueuedMessages(runId: string, _token: string, through: string) {
  const prefix = chatMessagePrefix(runId);
  const variables = await listChatVariables(prefix);
  const acknowledged = variables.filter((variable) => variable.name.slice(prefix.length) <= through);
  await Promise.all(acknowledged.map((variable) => deleteChatVariable(variable.name)));
  return acknowledged.length;
}

async function appendMessage(runId: string, token: string, entry: QueueMessage) {
  const prefix = chatMessagePrefix(runId);
  const existing = await listChatVariables(prefix);
  if (existing.length >= MAX_QUEUED_CHAT_MESSAGES) {
    throw new Error("chat queue is full; wait for the running agent to process messages");
  }
  const name = `${prefix}${entry.id}`;
  await createChatVariable(name, encryptQueue([entry], token));
  return entry;
}

export async function appendQueuedMessage(runId: string, token: string, message: string, clientId = "") {
  const prefix = chatMessagePrefix(runId);
  const existing = await listChatVariables(prefix);
  if (clientId) {
    for (const variable of existing) {
      let value = variable.value;
      if (typeof value !== "string") value = await readChatVariable(variable.name) || "";
      if (value && decryptQueue(value, token).some((item) => item.clientId === clientId)) {
        return decryptQueue(value, token)[0];
      }
    }
  }
  if (existing.length >= MAX_QUEUED_CHAT_MESSAGES) throw new Error("chat queue is full; wait for the running agent to process messages");
  const entry: QueueMessage = {
    id: `${Date.now().toString().padStart(13, "0")}_${randomBytes(8).toString("hex").toUpperCase()}`,
    clientId: clientId.slice(0, 80) || undefined,
    message: message.slice(0, MAX_CHAT_MESSAGE_CHARS),
    createdAt: new Date().toISOString(),
  };
  await createChatVariable(`${prefix}${entry.id}`, encryptQueue([entry], token));
  return entry;
}

export async function appendQueuedImage(runId: string, token: string, imageData: string,
                                        mimeType: string, fileName: string, clientId = "") {
  if (!/^image\/(jpeg|png|webp)$/.test(mimeType)) throw new Error("reference image must be JPEG, PNG, or WebP");
  const encoded = String(imageData || "").replace(/^data:image\/[a-zA-Z0-9.+-]+;base64,/, "");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded) || encoded.length % 4 !== 0) throw new Error("reference image is not valid base64");
  const raw = Buffer.from(encoded, "base64");
  if (!raw.length || raw.length > MAX_CHAT_IMAGE_BYTES) {
    throw new Error(`reference image must be no more than ${MAX_CHAT_IMAGE_BYTES} bytes after compression`);
  }
  const extension = mimeType === "image/jpeg" ? "jpg" : mimeType === "image/png" ? "png" : "webp";
  const entry: QueueMessage = {
    id: `${Date.now().toString().padStart(13, "0")}_${randomBytes(8).toString("hex").toUpperCase()}`,
    clientId: clientId.slice(0, 80) || undefined,
    message: `Supplied face reference image: ${String(fileName || `face-reference.${extension}`).replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 100)}. Save it, inspect its actual pixels, and style the Roblox face with one pair of bold dark eyebrows matching the visible shape; interpret “500+” as strong/dense brows, never hundreds of brows on one face. Do not identify or copy a real person's identity. The local AI must author inspect_image and ask its sub-agent to inspect/use this same reference with use_tools:true.`,
    createdAt: new Date().toISOString(), imageData: encoded, mimeType,
    fileName: `face-reference.${extension}`,
  };
  return appendMessage(runId, token, entry);
}

export async function deleteChatMessages(runId: string) {
  const prefix = chatMessagePrefix(runId);
  const variables = await listChatVariables(prefix);
  await Promise.all(variables.map((variable) => deleteChatVariable(variable.name)));
  return variables.length;
}
