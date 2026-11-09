#!/usr/bin/env python3
"""
NishAgent — the workflow agent that can search the web, create files,
create images, run commands in a sandbox, and delegate to the Gemini sub-agent.

This is the loop the `agent` workflow runs on the GitHub runner. It reuses the
same Ollama + Gemini stack the RBX-short workflow uses, so every model choice
in the RBX workflow (fast, medium, hard, smart_11b, animation_best) is also a
choice here. The model streams with the same coloured, letter-by-letter console
as the short workflow.

Capabilities exposed to the model as plain text tools (described in the system
prompt). The model returns JSON with `tool_calls` when it wants the runner to
do something; the runner executes it and feeds the result back for the next
round. This avoids needing a separate tool-calling API — the small local models
handle plain JSON well, and the loop is transparent in the log.

Tools:
  - search_web  : DuckDuckGo via ai_web_search.py (free, no key)
  - create_file : write any path under dist/agent_workspace
  - read_file   : read it back
  - list_files  : list the workspace
  - run_cmd     : execute a shell command in the sandbox (cwd = workspace)
  - create_image: render a prompt to a PNG via Pillow (placeholder for an
                  image model; keeps the workflow self-contained)
  - subagent    : delegate a code / writing / verify / name task to Gemini

When --tunnel is passed the agent also starts a tiny HTTP server on 8787 and
(if cloudflared is available) opens a free trycloudflare.com tunnel. The URL
is written to dist/tunnel_url.txt and to GITHUB_OUTPUT so the Vercel app can
retrieve it and talk live to the running workflow via the tunnel. Without the
tunnel the agent runs as a single batched job and writes all outputs to the
workspace artifact.

All tool use is logged to dist/agent_tools.jsonl and the chat history to
dist/agent_chat.json so the Vercel app can render the sidebar and the file
explorer from the workflow artifacts.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import paint  # noqa: E402

WORKSPACE = ROOT / "dist" / "agent_workspace"
CHAT_LOG = ROOT / "dist" / "agent_chat.json"
TOOLS_LOG = ROOT / "dist" / "agent_tools.jsonl"
TUNNEL_FILE = ROOT / "dist" / "tunnel_url.txt"
SYSTEM_FILE = ROOT / "dist" / "agent_system.txt"

MODEL_MAP = {
    "fast": "qwen3:4b",
    "medium": "qwen3:8b",
    "hard": "qwen3:8b",
    "smart_11b": "qwen3:14b",
    "animation_best": "deepseek-r1:8b",
}

DEFAULT_MODEL = "qwen3:8b"

TOOL_DOC = """
You are NishAgent, a helpful AI that lives inside a GitHub Actions sandbox.
You can do things in that sandbox by returning a JSON block. The workflow will
execute it and send you the result.

Available tools — return them as JSON exactly like this (inside ```json):

```json
{
  "tool_calls": [
    {"tool": "search_web", "query": "current price of bitcoin"},
    {"tool": "create_file", "path": "hello.py", "content": "print('hi')"},
    {"tool": "read_file", "path": "hello.py"},
    {"tool": "list_files", "path": "."},
    {"tool": "run_cmd", "cmd": "python hello.py"},
    {"tool": "create_image", "prompt": "a cute robot in a bedroom, soft lighting", "path": "robot.png"},
    {"tool": "subagent", "instruction": "write a clean function that...", "input": "optional context", "topic": "code"}
  ],
  "thought": "what you are doing and why",
  "answer": "your user-facing reply for this round (shown in the chat)"
}
```

Rules:
- `tool_calls` may be empty if you just want to answer — BUT for this workflow the SUB-AGENT IS MANDATORY AT THE START.
  In your FIRST JSON you MUST include at least one `subagent` call (topic code/models/map etc) for your hardest subtask. The helper is Gemini with a Groq fallback that tries the free best models llama-3.3-70b-versatile → qwen/qwen3-32b → llama-4-maverick → deepseek-r1-distill → openai/gpt-oss-120b → openai/gpt-oss-20b → llama-3.1-8b-instant (auto-retries with larger 16k window if cut), has the full file-rules guide, and returns provider, seconds, whether it edited a file, and FULL text. After it returns you MUST accept (include id in subagent_review and paste its result verbatim) or decline (leave out and build your own replacement) — never re-ask the same task twice and do not leave it empty.
  Keep each subagent instruction under 300 chars and focused: do NOT ask for an entire 20-page document with 50+ illustrations in one call — ask for a 1-page outline or a single section first, then expand in later rounds. The helper is capped at ~8k tokens (Groq now 8192→16384, Gemini 8192→16384) and will retry once if cut, but still keep requests focused.
- `path` is always relative to the workspace root (dist/agent_workspace). Do not use absolute paths or .. .
- `create_file` creates or overwrites; directories are made as needed.
- `run_cmd` runs a shell command with 60 s timeout; output is returned. Only use it for real tasks, not to list files (use list_files).
- `create_image` renders the prompt to a PNG file at `path`. Describe the image well; it is generated locally.
- `subagent` delegates to the Gemini helper (or Groq fallback). Use it for hard coding, writing, verifying or naming tasks. topic can be code, map, cameras, faces, narration, animation, models, or generic. Keep instruction precise — the helper knows shapes, materials, lights, 520 effects, grid/cast-lane/camera rules.
- `search_web` is free and requires no key; it appends facts the workflow sends back next round.
- After your tools run you will be asked again with their results. Keep going until the task is fully done, then return with no further tool_calls and a final answer.
- Think briefly — this runs on a CPU runner — and never repeat the same tool call twice.
- Be helpful, concise, and dark-grey-terminal-friendly in your tone. No disallowed content.
"""

def safe_path(p: str) -> Path:
    # Prevent escaping workspace
    raw = Path(p.strip().lstrip("/"))
    # drop .. parts
    parts = [part for part in raw.parts if part not in ("..", "")]
    target = WORKSPACE.joinpath(*parts) if parts else WORKSPACE / "unnamed"
    # ensure inside WORKSPACE
    try:
        target.resolve().relative_to(WORKSPACE.resolve())
    except Exception:
        # fallback to workspace root + sanitized name
        target = WORKSPACE / Path(p).name
    return target

def do_search(query: str) -> dict:
    from ai_web_search import search  # lazy
    results = search(query)
    return {"query": query, "results": results[:4], "count": len(results)}

def do_create_file(path: str, content: str) -> dict:
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content or "", encoding="utf-8")
    return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "bytes": len(content or ""), "full": str(target)}

def do_read_file(path: str) -> dict:
    target = safe_path(path)
    if not target.is_file():
        return {"ok": False, "error": f"no file at {path}"}
    try:
        text = target.read_text(encoding="utf-8")
        if len(text) > 8000:
            text = text[:8000] + "\n... truncated"
        return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "content": text}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def do_list_files(path: str) -> dict:
    base = safe_path(path) if path and path != "." else WORKSPACE
    if not base.exists():
        return {"ok": False, "error": f"no such dir {path}"}
    if base.is_file():
        return {"ok": True, "path": path, "files": [base.name]}
    files = []
    for child in sorted(base.rglob("*")):
        rel = child.relative_to(WORKSPACE)
        # hide deep nesting explosion
        if len(rel.parts) > 6:
            continue
        files.append(("dir/" if child.is_dir() else "") + str(rel))
        if len(files) > 120:
            files.append("... more")
            break
    return {"ok": True, "path": str(base.relative_to(WORKSPACE)) if base != WORKSPACE else ".", "files": files}

def do_run_cmd(cmd: str) -> dict:
    if not cmd.strip():
        return {"ok": False, "error": "empty cmd"}
    # security: block obviously destructive cmds in the workspace
    blocked = ["rm -rf /", "mkfs", ":(){:|:&};:"]
    if any(b in cmd for b in blocked):
        return {"ok": False, "error": "blocked command"}
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(WORKSPACE), capture_output=True, text=True, timeout=60)
        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > 8000:
            out = out[:8000] + "\n... truncated"
        return {"ok": proc.returncode == 0, "code": proc.returncode, "output": out, "cmd": cmd}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout after 60s", "cmd": cmd}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "cmd": cmd}

def do_create_image(prompt: str, path: str) -> dict:
    # Lightweight placeholder: render prompt text onto a gradient PNG via Pillow.
    # Self-contained runner has no external image model key; this keeps the
    # workflow green while showing a real downloadable file in the explorer.
    # If an image model key is ever added, replace this function with the API call.
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"Pillow not available: {exc}"}
    target = safe_path(path)
    if target.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        target = target.with_suffix(".png")
    target.parent.mkdir(parents=True, exist_ok=True)
    W, H = 1024, 576
    # vertical grey gradient
    img = Image.new("RGB", (W, H), "#1a1a1e")
    draw = ImageDraw.Draw(img)
    for y in range(H):
        # 26 -> 48 grey
        g = int(26 + (y / H) * 22)
        draw.line([(0, y), (W, y)], fill=(g, g, g + 2))
    # card
    pad = 48
    draw.rounded_rectangle([pad, pad, W - pad, H - pad], radius=28, fill="#2b2b30", outline="#3a3a40", width=2)
    # prompt
    try:
        # try to load a nicer font if present
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
    draw.text((pad + 32, pad + 32), "NishAgent — generated image", fill="#e8e8ea", font=font_title)
    # wrap prompt
    words = (prompt or "image").split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        # rough width check
        if len(test) * 11 > W - pad * 2 - 64:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    y = pad + 84
    for line in lines[:6]:
        draw.text((pad + 32, y), line, fill="#b8b8be", font=font_body)
        y += 30
    draw.text((pad + 32, H - pad - 28), f"prompt: {prompt[:84]}", fill="#808088", font=font_body)
    draw.text((W - pad - 220, H - pad - 28), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), fill="#606068", font=font_body)
    img.save(target, "PNG")
    return {"ok": True, "path": str(target.relative_to(WORKSPACE)), "prompt": prompt, "size": [W, H]}

def do_subagent(instruction: str, inp: str, topic: str) -> dict:
    # Call gemini_subagent.py for one task
    import tempfile, json as _json
    req = {"context": "nish agent task", "tasks": [{"id": "a1", "kind": "code" if topic == "code" else "answer", "instruction": instruction, "input": inp or "", "topic": topic or "code"}]}
    with tempfile.TemporaryDirectory() as td:
        rp = Path(td) / "req.json"
        op = Path(td) / "out.json"
        rp.write_text(_json.dumps(req), encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "tools" / "gemini_subagent.py"), "--request", str(rp), "--output", str(op), "--stdout"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = proc.stdout + proc.stderr
        if op.is_file():
            try:
                data = _json.loads(op.read_text(encoding="utf-8"))
                r = (data.get("results") or [{}])[0]
                return {"ok": bool(r.get("ok")), "text": (r.get("text") or "")[:16000], "model": data.get("model"), "raw": out[:4000]}
            except Exception as exc:
                return {"ok": False, "error": str(exc), "raw": out[:2000]}
        return {"ok": False, "error": "no output", "raw": out[:2000]}

TOOLS = {
    "search_web": lambda c: do_search(c.get("query") or c.get("q") or ""),
    "create_file": lambda c: do_create_file(c.get("path") or "output.txt", c.get("content") or c.get("text") or ""),
    "read_file": lambda c: do_read_file(c.get("path") or ""),
    "list_files": lambda c: do_list_files(c.get("path") or "."),
    "run_cmd": lambda c: do_run_cmd(c.get("cmd") or c.get("command") or ""),
    "create_image": lambda c: do_create_image(c.get("prompt") or c.get("description") or "", c.get("path") or "image.png"),
    "subagent": lambda c: do_subagent(c.get("instruction") or c.get("prompt") or "", c.get("input") or "", c.get("topic") or "code"),
}

def parse_tool_calls(text: str) -> dict | None:
    # Look for ```json block with tool_calls, or bare JSON
    import re
    # fenced json
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and "tool_calls" in obj:
                return obj
        except Exception:
            continue
    # try to find outermost JSON object with tool_calls
    try:
        # naive: find first { and last } that parses
        start = text.find('{"tool_calls"')
        if start != -1:
            # expand
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        cand = text[start:i+1]
                        obj = json.loads(cand)
                        if "tool_calls" in obj:
                            return obj
                        break
    except Exception:
        pass
    # bare {"tool_calls":...} anywhere
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict) and "tool_calls" in obj:
            return obj
    except Exception:
        pass
    return None

def load_chat() -> list[dict]:
    if CHAT_LOG.is_file():
        try:
            return json.loads(CHAT_LOG.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_chat(history: list[dict]) -> None:
    CHAT_LOG.parent.mkdir(parents=True, exist_ok=True)
    CHAT_LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def log_tool(tool: str, inp: dict, out: dict) -> None:
    TOOLS_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"time": datetime.now(timezone.utc).isoformat(), "tool": tool, "input": inp, "output": out}
    with TOOLS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def run_one_round(model: str, prompt: str, history: list[dict], label: str, enable_search: bool) -> tuple[str, dict | None]:
    # Build Ollama request
    messages = [{"role": "system", "content": TOOL_DOC + "\n\nWorkspace is dist/agent_workspace. You are running inside GitHub Actions; all file tools are sandboxed there."}]
    # add prior rounds
    for turn in history:
        if turn.get("role") == "user":
            messages.append({"role": "user", "content": turn["content"]})
        elif turn.get("role") == "assistant":
            messages.append({"role": "assistant", "content": turn["content"]})
        elif turn.get("role") == "tool":
            messages.append({"role": "user", "content": f"Tool result for {turn.get('tool')}: {json.dumps(turn.get('output'), ensure_ascii=False)[:12000]}"})
    messages.append({"role": "user", "content": prompt})
    req = {
        "model": model,
        "messages": messages,
        "think": True,
        "stream": False,
        "keep_alive": "60m",
        "options": {"temperature": 0.9, "num_predict": 8192, "num_ctx": 16384},
        "format": {"type": "object", "properties": {"thought": {"type": "string"}, "answer": {"type": "string"}, "tool_calls": {"type": "array", "items": {"type": "object"}}}, "required": ["answer"]},
    }
    # For local models that don't respect format strictly, we allow freeform too — parse fallback handles it.
    import tempfile, json as _json
    with tempfile.TemporaryDirectory() as td:
        rp = Path(td) / "req.json"
        op = Path(td) / "out.json"
        rp.write_text(_json.dumps(req), encoding="utf-8")
        # use ollama_stream for coloured output + streaming + fallback handling
        cmd = [sys.executable, str(ROOT / "tools" / "ollama_stream.py"), "--request", str(rp), "--output", str(op), "--label", label, "--timeout", "900"]
        # fallback model
        fallback = os.environ.get("AI_FALLBACK_MODEL", "qwen3:8b")
        if fallback:
            cmd += ["--fallback-model", fallback]
        print(paint(f"[{label}] calling {model} …", "label"), flush=True)
        proc = subprocess.run(cmd)
        if not op.is_file():
            raise SystemExit(f"{label}: no output from ollama_stream")
        data = _json.loads(op.read_text(encoding="utf-8"))
        text = data.get("response") or ""
        # The structured format gives us JSON string in response
        try:
            parsed = _json.loads(text) if text.strip().startswith("{") else None
        except Exception:
            parsed = None
        if parsed and isinstance(parsed, dict):
            # re-serialize for parse_tool_calls helper
            text_for_parse = _json.dumps(parsed)
        else:
            text_for_parse = text
            parsed = parse_tool_calls(text) or {}
            if not parsed:
                # treat whole answer as final
                parsed = {"answer": text, "thought": data.get("thinking") or "", "tool_calls": []}
        # also try to extract tool_calls from parsed if present
        tool_calls = parsed.get("tool_calls") or []
        answer = parsed.get("answer") or text
        thought = parsed.get("thought") or data.get("thinking") or ""
        # attach thinking for logging
        return answer, {"thought": thought, "answer": answer, "tool_calls": tool_calls, "raw": text}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, help="user prompt for the agent")
    ap.add_argument("--model", default="", help="ollama model name or preset fast/medium/hard/smart_11b/animation_best")
    ap.add_argument("--rounds", type=int, default=8, help="max tool rounds")
    ap.add_argument("--label", default="nish-agent")
    ap.add_argument("--tunnel", action="store_true", help="also start cloudflared tunnel for live chat")
    args = ap.parse_args()

    preset = (args.model or os.environ.get("MODEL_QUALITY") or "hard").strip().lower()
    model = MODEL_MAP.get(preset, preset if ":" in preset else DEFAULT_MODEL)
    if ":" not in model:
        model = MODEL_MAP.get(model.lower(), model)

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    # ensure gitignore inside workspace
    (WORKSPACE / ".gitkeep").write_text("", encoding="utf-8")

    prompt = args.prompt
    print(paint(f"[nish-agent] model: {model} (preset {preset})", "success"), flush=True)
    print(paint(f"[nish-agent] workspace: {WORKSPACE}", "plan"), flush=True)
    print(paint(f"[nish-agent] prompt: {prompt[:240]}", "label"), flush=True)

    # optional tunnel - live file + chat server
    tunnel_url = ""
    live_queue = ROOT / "dist" / "__live_queue.jsonl"
    if args.tunnel:
        try:
            import http.server, threading, socket, json as _j
            from urllib.parse import urlparse, parse_qs

            class LiveHandler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    try:
                        parsed = urlparse(self.path)
                        if parsed.path == "/__nish/files":
                            qs = parse_qs(parsed.query)
                            rel = (qs.get("path") or ["."])[0]
                            base = safe_path(rel) if rel and rel != "." else WORKSPACE
                            if not base.exists():
                                self.send_response(404); self.send_header("Content-Type","application/json"); self.end_headers()
                                self.wfile.write(_j.dumps({"ok": False, "error": f"no such dir {rel}"}).encode())
                                return
                            files = []
                            if base.is_file():
                                files = [str(base.relative_to(WORKSPACE))]
                            else:
                                for child in sorted(base.rglob("*")):
                                    try:
                                        relp = child.relative_to(WORKSPACE)
                                    except: continue
                                    if len(relp.parts) > 6: continue
                                    files.append(("dir/" if child.is_dir() else "") + str(relp))
                                    if len(files) > 200: break
                            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                            self.wfile.write(_j.dumps({"ok": True, "path": rel, "files": files, "count": len(files)}).encode())
                            return
                        if parsed.path == "/__nish/file":
                            qs = parse_qs(parsed.query)
                            rel = (qs.get("path") or [""])[0]
                            if not rel:
                                self.send_response(400); self.end_headers(); return
                            target = safe_path(rel)
                            if not target.is_file():
                                self.send_response(404); self.send_header("Content-Type","application/json"); self.end_headers()
                                self.wfile.write(_j.dumps({"ok": False, "error": f"no file {rel}"}).encode())
                                return
                            data = target.read_bytes()
                            ctype = "text/plain; charset=utf-8"
                            if target.suffix.lower() in (".png",".jpg",".jpeg"): ctype="image/png"
                            elif target.suffix.lower()==".json": ctype="application/json"
                            self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                            self.wfile.write(data)
                            return
                        if parsed.path == "/__nish/chat":
                            hist = load_chat()
                            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                            self.wfile.write(_j.dumps(hist).encode())
                            return
                        if parsed.path == "/__nish/tools":
                            txt = TOOLS_LOG.read_text(encoding="utf-8") if TOOLS_LOG.is_file() else ""
                            lines = [ _j.loads(l) for l in txt.strip().split("\n") if l.strip() ] if txt.strip() else []
                            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                            self.wfile.write(_j.dumps(lines[-40:]).encode())
                            return
                        if parsed.path == "/__nish/ping":
                            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
                            self.wfile.write(_j.dumps({"ok": True, "workspace": str(WORKSPACE), "files": len(list(WORKSPACE.rglob("*")))}).encode())
                            return
                        # fallback: serve static files from ROOT for Vercel preview
                        if ".." in parsed.path:
                            self.send_response(403); self.end_headers(); return
                        fpath = (ROOT / parsed.path.lstrip("/")).resolve()
                        try:
                            fpath.relative_to(ROOT.resolve())
                        except:
                            self.send_response(403); self.end_headers(); return
                        if fpath.is_dir():
                            fpath = fpath / "index.html"
                        if fpath.is_file():
                            self.send_response(200)
                            self.send_header("Content-Type","text/html" if fpath.suffix==".html" else "text/plain")
                            self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                            self.wfile.write(fpath.read_bytes())
                            return
                        self.send_response(404); self.end_headers()
                    except Exception as e:
                        try: self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())
                        except: pass
                def do_POST(self):
                    try:
                        parsed = urlparse(self.path)
                        length = int(self.headers.get("Content-Length") or 0)
                        body = self.rfile.read(length) if length else b""
                        if parsed.path in ("/__nish/chat", "/chat", "/api/chat"):
                            try: data = _j.loads(body.decode() or "{}")
                            except: data = {}
                            msg = str(data.get("message") or data.get("prompt") or "").strip()
                            if not msg:
                                self.send_response(400); self.send_header("Content-Type","application/json"); self.end_headers()
                                self.wfile.write(_j.dumps({"ok": False, "error": "message required"}).encode()); return
                            # append to chat and queue
                            hist = load_chat()
                            hist.append({"role": "user", "content": msg, "time": datetime.now(timezone.utc).isoformat(), "via": "live"})
                            save_chat(hist)
                            live_queue.parent.mkdir(parents=True, exist_ok=True)
                            with live_queue.open("a", encoding="utf-8") as f:
                                f.write(_j.dumps({"message": msg, "time": datetime.now(timezone.utc).isoformat()}) + "\n")
                            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                            self.wfile.write(_j.dumps({"ok": True, "queued": True, "message": msg[:200]}).encode())
                            return
                        self.send_response(404); self.end_headers()
                    except Exception as e:
                        try: self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())
                        except: pass
                def log_message(self, format, *args):
                    # suppress default log, we already print via paint if needed
                    return

            def serve():
                # do NOT chdir globally - handler uses absolute ROOT paths
                srv = http.server.HTTPServer(("127.0.0.1", 8787), LiveHandler)
                print(paint("[tunnel] live handler on 127.0.0.1:8787 — /__nish/files, /__nish/file, /__nish/chat", "tool"), flush=True)
                srv.serve_forever()
            t = threading.Thread(target=serve, daemon=True)
            t.start()
            print(paint("[tunnel] local server on 127.0.0.1:8787", "tool"), flush=True)
            # try cloudflared
            cf = subprocess.run(["which", "cloudflared"], capture_output=True, text=True)
            if cf.returncode == 0:
                proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:8787", "--no-autoupdate"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                start = time.time()
                url = ""
                while time.time() - start < 20:
                    line = proc.stdout.readline() if proc.stdout else ""
                    if not line:
                        time.sleep(0.3)
                        if proc.poll() is not None: break
                        continue
                    print(line, end="", flush=True)
                    if "trycloudflare.com" in line:
                        import re
                        m = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
                        if m:
                            url = m.group(0)
                            break
                if url:
                    tunnel_url = url
                    print(paint(f"[tunnel] live at {url} — files/chat live via /__nish/*", "success"), flush=True)
                    TUNNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
                    TUNNEL_FILE.write_text(url + "\n", encoding="utf-8")
                    gh_out = os.environ.get("GITHUB_OUTPUT")
                    if gh_out:
                        with open(gh_out, "a", encoding="utf-8") as f:
                            f.write(f"tunnel_url={url}\n")
                else:
                    print(paint("[tunnel] could not extract URL (continuing without live tunnel)", "warning"), flush=True)
            else:
                print(paint("[tunnel] cloudflared not installed; installing …", "warning"), flush=True)
                ok=False
                for attempt in range(1,5):
                    # robust curl with retry-all-errors and fallback to wget; handles 504 gateway from GitHub
                    res = subprocess.run("curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared || wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /tmp/cloudflared; test -s /tmp/cloudflared && chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/cloudflared", shell=True, timeout=60)
                    if pathlib.Path("/usr/local/bin/cloudflared").exists() and pathlib.Path("/usr/local/bin/cloudflared").stat().st_size > 100000:
                        ok=True
                        break
                    print(paint(f"[tunnel] install attempt {attempt} failed (curl 504?), retrying in {attempt*5}s", "warning"), flush=True)
                    time.sleep(attempt*5)
                    # cleanup partial
                    try: pathlib.Path("/tmp/cloudflared").unlink(missing_ok=True)
                    except: pass
                if ok:
                    print(paint("[tunnel] cloudflared installed, starting tunnel now…", "success"), flush=True)
                    cf2 = subprocess.run(["which", "cloudflared"], capture_output=True, text=True)
                    if cf2.returncode == 0:
                        proc2 = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:8787", "--no-autoupdate"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                        start2 = time.time()
                        url2 = ""
                        while time.time() - start2 < 20:
                            line = proc2.stdout.readline() if proc2.stdout else ""
                            if not line:
                                time.sleep(0.3)
                                if proc2.poll() is not None: break
                                continue
                            print(line, end="", flush=True)
                            if "trycloudflare.com" in line:
                                import re as _re2
                                m2 = _re2.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
                                if m2:
                                    url2 = m2.group(0)
                                    break
                        if url2:
                            tunnel_url = url2
                            print(paint(f"[tunnel] live at {url2} — files/chat live via /__nish/* (after install)", "success"), flush=True)
                            TUNNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
                            TUNNEL_FILE.write_text(url2 + "\n", encoding="utf-8")
                            gh_out2 = os.environ.get("GITHUB_OUTPUT")
                            if gh_out2:
                                with open(gh_out2, "a", encoding="utf-8") as f:
                                    f.write(f"tunnel_url={url2}\n")
                        else:
                            print(paint("[tunnel] still could not extract URL after install", "warning"), flush=True)
                else:
                    print(paint("[tunnel] cloudflared install failed after 3 attempts", "error"), flush=True)
        except Exception as exc:
            print(paint(f"[tunnel] failed: {exc} (continuing)", "warning"), flush=True)

    history: list[dict] = load_chat()
    # seed chat with user prompt
    history.append({"role": "user", "content": prompt, "time": datetime.now(timezone.utc).isoformat()})
    save_chat(history)

    # Also write system
    SYSTEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_FILE.write_text(TOOL_DOC, encoding="utf-8")

    current_prompt = prompt
    for rnd in range(1, args.rounds + 1):
        label = f"nish-agent r{rnd}/{args.rounds}"
        answer, parsed = run_one_round(model, current_prompt, history[:-1], label, True)
        if parsed is None:
            print(paint(f"[{label}] no parsed result, stopping", "error"), flush=True)
            break
        thought = parsed.get("thought") or ""
        tool_calls = parsed.get("tool_calls") or []
        # Enforce mandatory subagent on first round
        if rnd == 1 and not any(str(c.get("tool") or c.get("name") or "").lower() == "subagent" for c in tool_calls):
            print(paint(f"[{label}] first round missing subagent — injecting mandatory delegation", "warning"), flush=True)
            fallback_instr = f"Create a focused outline or core code for: {prompt[:150]} — keep under 300 chars, no full doc"
            tool_calls = [{"tool": "subagent", "instruction": fallback_instr, "input": prompt[:400], "topic": "code"}] + tool_calls
        # log thinking in coloured box (ollama_stream already did)
        print(paint(f"[agent thought] {thought[:220]}", "thinking"), flush=True)
        print(paint(f"[agent] {answer[:400]}", "answer"), flush=True)

        history.append({"role": "assistant", "content": answer, "thought": thought, "tool_calls": tool_calls, "round": rnd, "time": datetime.now(timezone.utc).isoformat()})
        save_chat(history)

        if not tool_calls:
            print(paint(f"[nish-agent] done after {rnd} round(s) — no more tool calls.", "success"), flush=True)
            break

        # execute tools
        results = []
        for call in tool_calls[:6]:  # cap
            tool = str(call.get("tool") or call.get("name") or "").strip().lower()
            # normalize
            if tool in ("web_search", "search"): tool = "search_web"
            if tool in ("write_file", "save_file"): tool = "create_file"
            if tool in ("exec", "shell", "bash"): tool = "run_cmd"
            if tool in ("image", "generate_image"): tool = "create_image"
            if tool not in TOOLS:
                out = {"ok": False, "error": f"unknown tool {tool}"}
                print(paint(f"[tool {tool}] unknown", "error"), flush=True)
            else:
                print(paint(f"[tool {tool}] {json.dumps(call)[:200]}", "tool"), flush=True)
                try:
                    out = TOOLS[tool](call)
                except Exception as exc:
                    out = {"ok": False, "error": str(exc)}
                print(paint(f"[tool {tool}] -> {json.dumps(out, ensure_ascii=False)[:2000]}", "plan"), flush=True)
            log_tool(tool, call, out)
            results.append({"tool": tool, "input": call, "output": out})

        # append tool results to history so next round sees them
        for r in results:
            history.append({"role": "tool", "tool": r["tool"], "output": r["output"], "time": datetime.now(timezone.utc).isoformat()})
        save_chat(history)

        # build next prompt as summary of results
        current_prompt = "Tool results:\\n" + json.dumps(results, ensure_ascii=False, indent=2)[:20000] + "\\n\\nContinue the task. If you are done, reply with no tool_calls and a final summary. If you still need to do work, return the next tool_calls."

        # brief pause
        time.sleep(0.3)

    # Persistent live mode — this Run NishAgent step stays as the last plan until workflow dies,
    # streaming thinking/tools/files via direct GitHub API (log tail + artifact). This replaces the separate
    # Keep runner alive step and the Post Checkout noise — the last visible plan is now the AI itself.
    try:
        print(paint("[nish-agent live] entering persistent live mode — this plan will stay active until workflow timeout, streaming via direct GitHub API (no Cloudflare needed)...", "success"), flush=True)
        # prepare live queue offset (messages sent from website via tunnel if enabled, otherwise just heartbeat)
        seen_lines = 0
        if live_queue.is_file():
            try:
                seen_lines = len([l for l in live_queue.read_text(encoding="utf-8").splitlines() if l.strip()])
            except:
                seen_lines = 0
        for live_i in range(600):  # 600*10s = 100m, fits 120m timeout
            # check for new live messages queued via /__nish/chat (tunnel or local)
            if live_queue.is_file():
                try:
                    lines = [l for l in live_queue.read_text(encoding="utf-8").splitlines() if l.strip()]
                    if len(lines) > seen_lines:
                        new = lines[seen_lines:]
                        seen_lines = len(lines)
                        for raw in new:
                            try:
                                import json as _jl
                                data = _jl.loads(raw)
                            except:
                                continue
                            msg = str(data.get("message") or data.get("prompt") or "").strip()
                            if not msg:
                                continue
                            print(paint(f"[live message] {msg[:300]}", "tool"), flush=True)
                            # append as user and run one more AI round inside this same plan
                            history.append({"role": "user", "content": msg, "time": datetime.now(timezone.utc).isoformat(), "via": "live"})
                            save_chat(history)
                            label = f"nish-agent live {live_i+1}"
                            try:
                                answer2, parsed2 = run_one_round(model, msg, history[:-1], label, True)
                            except Exception as e:
                                print(paint(f"[live] model call failed: {e}", "error"), flush=True)
                                continue
                            thought2 = (parsed2 or {}).get("thought") or ""
                            tool_calls2 = (parsed2 or {}).get("tool_calls") or []
                            answer2 = (parsed2 or {}).get("answer") or answer2 or ""
                            print(paint(f"[agent thought] {thought2[:260]}", "thinking"), flush=True)
                            print(paint(f"[agent] {answer2[:500]}", "answer"), flush=True)
                            history.append({"role": "assistant", "content": answer2, "thought": thought2, "tool_calls": tool_calls2, "time": datetime.now(timezone.utc).isoformat()})
                            save_chat(history)
                            if tool_calls2:
                                results2 = []
                                for call in tool_calls2[:6]:
                                    tool = str(call.get("tool") or call.get("name") or "").strip().lower()
                                    if tool in ("web_search", "search"): tool = "search_web"
                                    if tool in ("write_file", "save_file"): tool = "create_file"
                                    if tool in ("exec", "shell", "bash"): tool = "run_cmd"
                                    if tool in ("image", "generate_image"): tool = "create_image"
                                    if tool not in TOOLS:
                                        out = {"ok": False, "error": f"unknown tool {tool}"}
                                        print(paint(f"[tool {tool}] unknown", "error"), flush=True)
                                    else:
                                        print(paint(f"[tool {tool}] {json.dumps(call)[:240]}", "tool"), flush=True)
                                        try:
                                            out = TOOLS[tool](call)
                                        except Exception as exc:
                                            out = {"ok": False, "error": str(exc)}
                                        print(paint(f"[tool {tool}] -> {json.dumps(out, ensure_ascii=False)[:2200]}", "plan"), flush=True)
                                    log_tool(tool, call, out)
                                    results2.append({"tool": tool, "input": call, "output": out})
                                for r in results2:
                                    history.append({"role": "tool", "tool": r["tool"], "output": r["output"], "time": datetime.now(timezone.utc).isoformat()})
                                save_chat(history)
                            # refresh preview for direct API polling (no tunnel needed)
                            try:
                                (ROOT / "dist" / "preview").mkdir(parents=True, exist_ok=True)
                                (ROOT / "dist" / "preview" / "agent_chat.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
                                if TOOLS_LOG.is_file():
                                    (ROOT / "dist" / "preview" / "agent_tools.jsonl").write_text(TOOLS_LOG.read_text(encoding="utf-8"), encoding="utf-8")
                            except Exception:
                                pass
                except Exception as e:
                    print(paint(f"[live] queue check failed: {e}", "warning"), flush=True)
            if live_i % 6 == 0:
                print(paint(f"[nish-agent live] heartbeat {live_i}/600 — {len(list(WORKSPACE.rglob('*')))} files — {len(history)} messages — {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC — direct API polling active", "plan"), flush=True)
                try:
                    (ROOT / "dist" / "preview").mkdir(parents=True, exist_ok=True)
                    (ROOT / "dist" / "preview" / "agent_chat.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
                    if TOOLS_LOG.is_file():
                        (ROOT / "dist" / "preview" / "agent_tools.jsonl").write_text(TOOLS_LOG.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
            time.sleep(10)
        print(paint("[nish-agent live] persistent mode finished — workflow will now complete and upload artifacts", "success"), flush=True)
    except Exception as exc:
        print(paint(f"[live] persistent loop ended: {exc}", "warning"), flush=True)

    # legacy tunnel hint (now direct API)

    # final summary to step summary
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write("\n## NishAgent — run summary\n\n")
            out.write(f"- **Model:** {model} (preset {preset})\n")
            out.write(f"- **Prompt:** {prompt[:300]}\n")
            out.write(f"- **Rounds:** {len([h for h in history if h.get('role')=='assistant'])}\n")
            out.write(f"- **Workspace:** `dist/agent_workspace` ({len(list(WORKSPACE.rglob('*')))} files)\n")
            if tunnel_url:
                out.write(f"- **Live tunnel:** {tunnel_url}\n")
            out.write(f"- **Chat log:** `dist/agent_chat.json` — {len(history)} messages\n")
            out.write(f"- **Tool log:** `dist/agent_tools.jsonl`\n")

    print(paint("[nish-agent] chat saved to dist/agent_chat.json", "success"), flush=True)
    print(paint("[nish-agent] tools saved to dist/agent_tools.jsonl", "success"), flush=True)
    print(paint("[nish-agent] workspace at dist/agent_workspace — open it in the Vercel explorer", "plan"), flush=True)
    if tunnel_url:
        print(paint(f"[nish-agent] live tunnel: {tunnel_url}", "success"), flush=True)

if __name__ == "__main__":
    main()
