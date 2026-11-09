# NishAgent — nishagent.vercel.app

Dark grey studio for two workflows in this repo:

- **Agent chat** (`/`) — the new `agent.yml` workflow. It runs a local Ollama model (same choices as the short workflow: `fast`, `medium`, `hard`, `smart_11b`, `animation_best` — `hard` recommended for agent) and can:
  - `search_web` (DuckDuckGo via `tools/ai_web_search.py`, free)
  - `create_file` / `read_file` / `list_files` under `dist/agent_workspace`
  - `run_cmd` in the sandbox
  - `create_image` (Pillow-rendered PNG)
  - `subagent` — delegates to Gemini (or Groq fallback) for code/writing/verify

  Chat history → `dist/agent_chat.json`, tool calls → `dist/agent_tools.jsonl`, workspace → `dist/agent_workspace`. All uploaded as artifacts and shown in the Vercel file explorer (other side of the chat) with open / download / folder navigation.

  **Live mode**: tick *Enable Cloudflare tunnel* in the New chat modal — the runner installs `cloudflared` and exposes `https://…trycloudflare.com` (free). Vercel proxies user messages through `/api/agent/chat` → tunnel so you can talk live to the running job. Without it, batch mode + artifact polling every 4s.

- **RBX Short** (`/rbxshort` alias `nishagent.vercel.app/rbxshort`) — the existing `main.yml` workflow. Same inputs as GitHub: story topic, usernames, duration, map detail, model, voice, theme. Dispatches via `GITHUB_TOKEN` and shows coloured logs + plan next/previous loads.

## Secure by default

- The repo never stores a token. Vercel holds `GITHUB_TOKEN` as an **Environment Variable** (Settings → Environment Variables → `GITHUB_TOKEN` — a fine-grained PAT with `Actions: read/write`, `Contents: read` on `Nishgamerrz/Ai-rant`).
- All `/api/github/*` routes read it server-side. The browser never sees it. The token is never logged.
- Cloudflare tunnel host is allow-listed to `*.trycloudflare.com`.

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
