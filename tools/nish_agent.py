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
- `tool_calls` may be empty if you just want to answer.
- `path` is always relative to the workspace root (dist/agent_workspace). Do not use absolute paths or .. .
- `create_file` creates or overwrites; directories are made as needed.
- `run_cmd` runs a shell command with 60 s timeout; output is returned. Only use it for real tasks, not to list files (use list_files).
- `create_image` renders the prompt to a PNG file at `path`. Describe the image well; it is generated locally.
- `subagent` delegates to the Gemini helper (or Groq fallback). Use it for hard coding, writing, verifying or naming tasks. topic can be code, map, cameras, faces, narration, animation, models, or generic. Keep instruction precise.
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
                return {"ok": bool(r.get("ok")), "text": (r.get("text") or "")[:8000], "model": data.get("model"), "raw": out[:2000]}
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
            messages.append({"role": "user", "content": f"Tool result for {turn.get('tool')}: {json.dumps(turn.get('output'), ensure_ascii=False)[:7000]}"})
    messages.append({"role": "user", "content": prompt})
    req = {
        "model": model,
        "messages": messages,
        "think": True,
        "stream": False,
        "keep_alive": "60m",
        "options": {"temperature": 0.9, "num_predict": 4096, "num_ctx": 8192},
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

    # optional tunnel
    tunnel_url = ""
    if args.tunnel:
        try:
            import http.server, threading, socket
            from urllib.parse import urlparse
            # tiny server on 8787 that replays workspace files + chat
            handler = http.server.SimpleHTTPRequestHandler
            # run in thread
            def serve():
                import http.server
                os.chdir(str(ROOT))
                srv = http.server.HTTPServer(("127.0.0.1", 8787), handler)
                srv.serve_forever()
            t = threading.Thread(target=serve, daemon=True)
            t.start()
            print(paint("[tunnel] local server on 127.0.0.1:8787", "tool"), flush=True)
            # try cloudflared
            cf = subprocess.run(["which", "cloudflared"], capture_output=True, text=True)
            if cf.returncode == 0:
                proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:8787", "--no-autoupdate"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                # read for URL for up to 20s
                start = time.time()
                url = ""
                while time.time() - start < 20:
                    line = proc.stdout.readline() if proc.stdout else ""
                    if not line:
                        time.sleep(0.5)
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
                    print(paint(f"[tunnel] live at {url}", "success"), flush=True)
                    TUNNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
                    TUNNEL_FILE.write_text(url + "\n", encoding="utf-8")
                    gh_out = os.environ.get("GITHUB_OUTPUT")
                    if gh_out:
                        with open(gh_out, "a", encoding="utf-8") as f:
                            f.write(f"tunnel_url={url}\n")
                else:
                    print(paint("[tunnel] could not extract URL (continuing without live tunnel)", "warning"), flush=True)
            else:
                # try download
                print(paint("[tunnel] cloudflared not installed; installing …", "warning"), flush=True)
                subprocess.run("curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/cloudflared", shell=True, timeout=30)
                print(paint("[tunnel] installed, retry — tunnel URL will be in logs", "tool"), flush=True)
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
                print(paint(f"[tool {tool}] -> {json.dumps(out, ensure_ascii=False)[:400]}", "plan"), flush=True)
            log_tool(tool, call, out)
            results.append({"tool": tool, "input": call, "output": out})

        # append tool results to history so next round sees them
        for r in results:
            history.append({"role": "tool", "tool": r["tool"], "output": r["output"], "time": datetime.now(timezone.utc).isoformat()})
        save_chat(history)

        # build next prompt as summary of results
        current_prompt = "Tool results:\n" + json.dumps(results, ensure_ascii=False, indent=2) + "\n\nContinue the task. If you are done, reply with no tool_calls and a final summary. If you still need to do work, return the next tool_calls."

        # brief pause
        time.sleep(0.3)

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
