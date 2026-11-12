# NishAgent — nishagent.vercel.app

Dark grey studio for two workflows in this repo:

- **Agent chat** (`/`) — the `agent.yml` workflow. It runs a local Ollama model (choices: `fast`, `medium`, `hard`, `smart_11b`, `animation_best`) with twenty shared tools available to both the local model and a tool-enabled Gemini/Groq sub-agent:
  - web and visual/model asset-reference search (`search_web`, `search_assets`, `find_model_reference`)
  - safe workspace file create/read/list/search/exact edit plus bounded shell commands
  - HTTPS image download, Gemini pixel inspection, resize/crop/convert/compare/contact-sheet, Gemini image generation/editing
  - video metadata inspection and ZIP packaging
  - `subagent` — Gemini first, then Groq fallback for complete answers and model-authored visual/file tool calls

  Chat history → `dist/agent_chat.json`, tool calls → `dist/agent_tools.jsonl`, workspace → `dist/agent_workspace`. All uploaded as artifacts and shown in the Vercel file explorer (other side of the chat) with open / download / folder navigation.

  **Live chat**: the website dispatches the workflow with a random, run-scoped key. The workflow registers it with the website using a signed GitHub Actions OIDC proof (same run/repository/workflow). Follow-up text and compressed face-reference images are AES-GCM encrypted into per-message GitHub Actions variables; the single persistent agent plan polls and acknowledges them through the GitHub API. Logs and artifacts are also read directly from GitHub — no tunnel or sidecar server.

- **RBX Short** (`/rbxshort` alias `nishagent.vercel.app/rbxshort`) — the existing `main.yml` workflow. Same inputs as GitHub: story topic, usernames, duration, map detail, model, voice, theme. Dispatches via `GITHUB_TOKEN` and shows coloured logs + plan next/previous loads.

## Secure by default

- The repo never stores a token. Vercel holds `GITHUB_TOKEN` as an **Environment Variable** (Settings → Environment Variables → `GITHUB_TOKEN` — a fine-grained PAT with `Actions: read/write`, `Contents: read` on `Nishgamerrz/Ai-rant`).
- All `/api/github/*` routes read it server-side. The browser never sees it. The token is never logged.
- Chat registration is rejected unless a short-lived GitHub Actions OIDC token is signed by GitHub and is bound to the expected repository, `agent.yml`, `workflow_dispatch` event, and run ID. The browser can use a registered token but cannot claim a new run session.
- Chat actions variables store only encrypted queue payloads and a hash of the run-scoped key. Vercel's server-side `GITHUB_TOKEN` needs Actions variables read/write access; the workflow token is limited to `actions: read`, `contents: read`, and `id-token: write`.

## Local dev

```bash
cd web
npm install
# Set a PAT for local dispatch (never commit it)
export GITHUB_TOKEN=ghp_xxx
npm run dev  # http://0.0.0.0:3000
```

## Deploy to Vercel (nishagent.vercel.app)

1. Import `Nishgamerrz/Ai-rant` in Vercel → Framework: Next.js, Root Directory: `web` (or keep vercel.json which does `cd web`).
2. Add Environment Variable `GITHUB_TOKEN` (Production + Preview + Development).
3. Deploy. `nishagent.vercel.app` and `nishagent.vercel.app/rbxshort` will be live.
4. Click **＋ New chat** → pick **Agent** or **RBX Short**, choose model (Hard for agent), and Run. Watch logs in colours; open files on the right.

## How the “very good dark gui grey gui” is built

- Tailwind with a low-saturation grey palette (`#0e0e10`, `#1a1a1e`, `#222228`, `#2c2c32`), rounded-2xl cards, mono logs.
- Log colours match `tools/console_style.py` (thinking grey, answer cyan, tool violet, success green) so what you see live is what the runner prints.
- Sidebar is a full-height drawer on mobile and a sticky panel on desktop — every chat is a workflow run from `/api/github/runs`.
- File explorer reads artifacts via `/api/github/artifact` (zip → JSZip), so any path the AI created can be opened, previewed, or downloaded as a zip.
