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

Tools (the same twenty are available to the Gemini/Groq sub-agent when
`use_tools: true` is authored in its delegation call):
  - web and Roblox/model asset-reference search
  - safe workspace file creation, reading, listing, search, and exact edits
  - bounded shell commands with provider credentials stripped
  - HTTPS image download, visual image inspection, generation, and reference edits
  - image resize/crop/convert/compare/contact sheets, video inspection, ZIP packaging
  - Gemini/Groq code, writing, verification, and naming delegation

The agent stays in its original workflow run and polls GitHub Actions variables
for encrypted website messages. It uses direct GitHub API access only; no tunnel
or extra service is opened.

All tool use is logged to dist/agent_tools.jsonl and the chat history to
dist/agent_chat.json so the Vercel app can render the sidebar and the file
explorer from the workflow artifacts.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import paint  # noqa: E402
from agent_tools import TOOL_GUIDE, TOOL_NAMES, execute_tool  # noqa: E402

WORKSPACE = ROOT / "dist" / "agent_workspace"
CHAT_LOG = ROOT / "dist" / "agent_chat.json"
TOOLS_LOG = ROOT / "dist" / "agent_tools.jsonl"
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
- The SUB-AGENT IS MANDATORY AT THE START. Your FIRST JSON must itself author a useful `subagent` call with a non-empty instruction for the hardest subtask. The runner will reject and re-ask if you omit it; it will never invent or inject a delegation call. The helper is Gemini with a Groq fallback that tries llama-3.3-70b-versatile first, then openai/gpt-oss-120b if the first model is retired, rate-limited, or still cuts off after the 16k retry; other configured models are last-resort fallbacks. It returns provider, seconds, whether it edited a file, and FULL text. Set `use_tools: true` when the helper needs to search, inspect, or edit a visual reference.
  Keep each subagent instruction under 300 chars and focused: do NOT ask for an entire 20-page document with 50+ illustrations in one call — ask for a 1-page outline or a single section first, then expand in later rounds. The helper is capped at ~8k tokens (Groq now 8192→16384, Gemini 8192→16384) and will retry once if cut, but still keep requests focused.
- `path` is always relative to the workspace root (dist/agent_workspace). Do not use absolute paths or .. .
- `create_file` creates or overwrites; directories are made as needed.
- `run_cmd` runs a shell command with 60 s timeout; output is returned. Only use it for real tasks, not to list files (use list_files).
- Image generation requires the configured Gemini image model; it produces real pixels rather than a prompt-card placeholder.
- `subagent` delegates to the Gemini helper (or Groq fallback). Use it for hard coding, writing, verifying or naming tasks. Set `use_tools: true` when the helper should search or inspect visual references. Keep instruction precise — the helper knows shapes, materials, lights, 520 effects, grid/cast-lane/camera rules.
- The first map/camera plan must itself author the required delegation call(s); workflow-injected calls do not count.
- After your tools run you will be asked again with their results. Keep going until the task is fully done, then return with no further tool_calls and a final answer.
- Think briefly — this runs on a CPU runner — and never repeat the same tool call twice.
- Be helpful, concise, and dark-grey-terminal-friendly in your tone. No disallowed content.
""" + "\n\n" + TOOL_GUIDE

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

def do_subagent(instruction: str, inp: str, topic: str, use_tools: bool = False) -> dict:
    # Call gemini_subagent.py for one task. Tool-enabled work runs in the same
    # workspace as the parent so image references and edits are immediately visible.
    import tempfile, json as _json
    req = {"context": "nish agent task", "tasks": [{"id": "a1", "kind": "agent" if use_tools else ("code" if topic == "code" else "answer"), "instruction": instruction, "input": inp or "", "topic": topic or "code"}]}
    with tempfile.TemporaryDirectory() as td:
        rp = Path(td) / "req.json"
        op = Path(td) / "out.json"
        rp.write_text(_json.dumps(req), encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "tools" / "gemini_subagent.py"), "--request", str(rp), "--output", str(op), "--stdout"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=str(WORKSPACE))
        out = proc.stdout + proc.stderr
        if op.is_file():
            try:
                data = _json.loads(op.read_text(encoding="utf-8"))
                r = (data.get("results") or [{}])[0]
                return {"ok": bool(r.get("ok")), "text": (r.get("text") or "")[:16000],
                        "model": data.get("model"), "provider": r.get("provider"),
                        "providers": r.get("providers", []), "tool_rounds": r.get("tool_rounds", 0),
                        "tool_calls": r.get("tool_calls", []), "tool_results": r.get("tool_results", []),
                        "raw": out[:4000]}
            except Exception as exc:
                return {"ok": False, "error": str(exc), "raw": out[:2000]}
        return {"ok": False, "error": "no output", "raw": out[:2000]}

def _shared_tool(name: str):
    return lambda call: execute_tool(name, call, WORKSPACE)


# The same twenty tools are available to the parent and, when requested, to the
# Gemini/Groq sub-agent. The model must author a tool call in its response; this
# map contains executors only and never injects a call on the model's behalf.
TOOLS = {name: _shared_tool(name) for name in TOOL_NAMES}
TOOLS["create_image"] = lambda call: execute_tool(
    "generate_image", {"prompt": call.get("prompt") or call.get("description") or "",
                       "output": call.get("output") or call.get("path") or "image.png"}, WORKSPACE)
TOOLS["read_image"] = TOOLS["inspect_image"]
TOOLS["subagent"] = lambda call: do_subagent(
    call.get("instruction") or call.get("prompt") or "", call.get("input") or "",
    call.get("topic") or "code",
    use_tools=(call.get("use_tools") is True or str(call.get("use_tools") or "").strip().lower() in ("true", "1", "yes", "on")))

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
        cmd = [
            sys.executable, str(ROOT / "tools" / "ollama_stream.py"),
            "--request", str(rp), "--output", str(op), "--label", label,
            "--timeout", "900", "--stall-seconds", os.environ.get("AI_STALL", "900"),
        ]
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

def _chat_key_bytes() -> bytes:
    token = os.environ.get("AGENT_CHAT_KEY", "").strip()
    if not token:
        return b""
    try:
        key = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, base64.binascii.Error):
        return b""
    return key if len(key) == 32 else b""


def poll_remote_chat(after: str = "") -> list[dict]:
    """Fetch/decrypt this run's individually encrypted GitHub Actions variables."""
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    key = _chat_key_bytes()
    if not run_id or not token or not key:
        return []
    prefix = f"NISH_AGENT_MSG_{run_id}_"
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    messages: list[dict] = []
    for page in range(1, 6):
        url = f"https://api.github.com/repos/Nishgamerrz/Ai-rant/actions/variables?per_page=100&page={page}"
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Ai-rant-agent-chat/1.0",
        })
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub live-message poll returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"GitHub live-message poll failed: {type(exc).__name__}: {exc}") from exc
        variables = payload.get("variables", []) if isinstance(payload, dict) else []
        for variable in variables:
            name = str(variable.get("name") or "")
            if not name.startswith(prefix):
                continue
            try:
                encrypted = json.loads(str(variable.get("value") or ""))
                iv = base64.b64decode(encrypted["iv"], validate=True)
                tag = base64.b64decode(encrypted["tag"], validate=True)
                data = base64.b64decode(encrypted["data"], validate=True)
                clear = AESGCM(key).decrypt(iv, data + tag, None)
                queue = json.loads(clear.decode("utf-8"))
                if queue.get("v") == 1 and isinstance(queue.get("messages"), list):
                    messages.extend(item for item in queue["messages"] if isinstance(item, dict)
                                    and isinstance(item.get("id"), str)
                                    and isinstance(item.get("message"), str)
                                    and item["id"] > after)
            except Exception as exc:
                print(paint(f"[live chat] ignored unreadable encrypted message variable {name}: {type(exc).__name__}", "warning"), flush=True)
        if len(variables) < 100 or page * 100 >= int(payload.get("total_count", 0)):
            break
    return sorted(messages, key=lambda item: item["id"])


def acknowledge_remote_chat(message_id: str) -> bool:
    """Ask the authenticated Vercel endpoint to remove messages already processed."""
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    token = os.environ.get("AGENT_CHAT_KEY", "").strip()
    endpoint = os.environ.get("AGENT_CHAT_URL", "https://nishagent.vercel.app/api/agent/chat").strip()
    if not (run_id and token and endpoint):
        return False
    body = json.dumps({"runId": run_id, "action": "ack", "through": message_id}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": "Ai-rant-agent-chat/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
            return response.status < 300 and bool(payload.get("ok"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        print(paint(f"[live chat] acknowledgement failed ({type(exc).__name__}); the run keeps its local cursor.", "warning"), flush=True)
        return False


def stage_reference_image(item: dict) -> str:
    encoded = str(item.get("imageData") or "")
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > 24_000:
        raise ValueError("reference image is empty or larger than the 24 KB compressed limit")
    mime = str(item.get("mimeType") or "")
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("reference image must be JPEG, PNG, or WebP")
    from io import BytesIO
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 4_000_000
    with Image.open(BytesIO(raw)) as image:
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        stamp = str(item.get("id") or "latest").split("_", 1)[0]
        if not stamp.isdecimal():
            stamp = "latest"
        relative = Path("references") / f"face-reference-{stamp}.jpg"
        target = safe_path(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="JPEG", quality=90, optimize=True)
    return relative.as_posix()


def save_preview(history: list[dict]) -> None:
    try:
        preview = ROOT / "dist" / "preview"
        preview.mkdir(parents=True, exist_ok=True)
        (preview / "agent_chat.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        if TOOLS_LOG.is_file():
            (preview / "agent_tools.jsonl").write_text(TOOLS_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass


def normalize_agent_tool_call(call: dict, tool: str = "") -> dict:
    """Flatten either inline tool arguments or the common nested JSON shape."""
    name = tool or str(call.get("tool") or call.get("name") or "").strip().lower()
    raw_arguments = call.get("arguments")
    if isinstance(raw_arguments, str):
        try:
            raw_arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            raw_arguments = {}
    normalized = {key: value for key, value in call.items()
                  if key not in ("tool", "name", "arguments", "thought", "answer")}
    if isinstance(raw_arguments, dict):
        normalized.update(raw_arguments)
    normalized["tool"] = name
    return normalized


def execute_agent_tools(tool_calls: list[dict], label: str) -> list[dict]:
    results: list[dict] = []
    for authored_call in (tool_calls or [])[:6]:
        if not isinstance(authored_call, dict):
            continue
        tool = str(authored_call.get("tool") or authored_call.get("name") or "").strip().lower()
        if tool in ("web_search", "search"):
            tool = "search_web"
        if tool in ("write_file", "save_file"):
            tool = "create_file"
        if tool in ("exec", "shell", "bash"):
            tool = "run_cmd"
        if tool in ("image", "generate_image"):
            tool = "create_image"
        call = normalize_agent_tool_call(authored_call, tool)
        if tool not in TOOLS:
            out = {"ok": False, "error": f"unknown tool {tool}"}
            print(paint(f"[tool {tool}] unknown", "error"), flush=True)
        else:
            print(paint(f"[tool {tool}] {json.dumps(call, ensure_ascii=False)[:240]}", "tool"), flush=True)
            try:
                out = TOOLS[tool](call)
            except Exception as exc:
                out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:1200]}
            print(paint(f"[tool {tool}] -> {json.dumps(out, ensure_ascii=False)[:2200]}", "plan"), flush=True)
        log_tool(tool, authored_call, out)
        results.append({"tool": tool, "input": authored_call, "output": out})
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, help="user prompt for the agent")
    ap.add_argument("--model", default="", help="ollama model name or preset fast/medium/hard/smart_11b/animation_best")
    ap.add_argument("--rounds", type=int, default=8, help="max tool rounds")
    ap.add_argument("--label", default="nish-agent")
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
    print(paint(f"[nish-agent] prompt received ({len(prompt)} characters)", "label"), flush=True)

    history: list[dict] = load_chat()
    # seed chat with user prompt
    history.append({"role": "user", "content": prompt, "time": datetime.now(timezone.utc).isoformat()})
    save_chat(history)

    # Also write system
    SYSTEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_FILE.write_text(TOOL_DOC, encoding="utf-8")

    current_prompt = prompt
    delegation_satisfied = False
    for rnd in range(1, args.rounds + 1):
        label = f"nish-agent r{rnd}/{args.rounds}"
        answer, parsed = run_one_round(model, current_prompt, history[:-1], label, True)
        if parsed is None:
            print(paint(f"[{label}] no parsed result, stopping", "error"), flush=True)
            break
        thought = parsed.get("thought") or ""
        tool_calls = parsed.get("tool_calls") or []
        # The local AI must author its required delegation; no workflow-side injection.
        authored_subagent = False
        for candidate in tool_calls:
            if not isinstance(candidate, dict):
                continue
            normalized = normalize_agent_tool_call(candidate)
            if (normalized.get("tool") == "subagent"
                    and bool(str(normalized.get("instruction") or normalized.get("prompt") or "").strip())):
                authored_subagent = True
                break
        if not delegation_satisfied and not authored_subagent:
            print(paint(f"[{label}] first response omitted the AI-authored subagent call; rejecting it and asking the model to write the required call itself.", "warning"), flush=True)
            current_prompt = (
                "Your preceding first response was rejected because it did not itself "
                "author a non-empty subagent tool call. This is mandatory: write a "
                "useful subagent object with a non-empty instruction in your own "
                "JSON tool_calls now. Do not claim the runner called it."
            )
            continue
        if authored_subagent:
            delegation_satisfied = True
        # log thinking in coloured box (ollama_stream already did)
        print(paint(f"[agent thought] {thought[:220]}", "thinking"), flush=True)
        print(paint(f"[agent] {answer[:400]}", "answer"), flush=True)

        history.append({"role": "assistant", "content": answer, "thought": thought, "tool_calls": tool_calls, "round": rnd, "time": datetime.now(timezone.utc).isoformat()})
        save_chat(history)

        if not tool_calls:
            print(paint(f"[nish-agent] done after {rnd} round(s) — no more tool calls.", "success"), flush=True)
            break

        # execute tools
        results = execute_agent_tools(tool_calls, label)
        # append tool results to history so next round sees them
        for r in results:
            history.append({"role": "tool", "tool": r["tool"], "output": r["output"], "time": datetime.now(timezone.utc).isoformat()})
        save_chat(history)

        # build next prompt as summary of results
        current_prompt = "Tool results:\\n" + json.dumps(results, ensure_ascii=False, indent=2)[:20000] + "\\n\\nContinue the task. If you are done, reply with no tool_calls and a final summary. If you still need to do work, return the next tool_calls."

        # brief pause
        time.sleep(0.3)

    if not delegation_satisfied:
        print(paint("[nish-agent] local model never authored the mandatory subagent call; refusing to mark its plan complete.", "error"), flush=True)
        raise RuntimeError("local model failed to author a non-empty subagent tool call within the configured round limit")

    def process_live_message(item: dict, live_index: int) -> bool:
        msg = str(item.get("message") or item.get("prompt") or "").strip()
        if not msg:
            return True
        reference_path = ""
        if item.get("imageData"):
            try:
                reference_path = stage_reference_image(item)
                msg += (
                    f"\\nA supplied face reference is saved at `{reference_path}` in your workspace. "
                    "Before changing the face design, you and your sub-agent must inspect the actual pixels. "
                    "Your own JSON must author an inspect_image call for this path and a subagent call with use_tools:true; "
                    "the helper must inspect the same file. Match its bold dark eyebrow style as one expressive pair per face, "
                    "not hundreds of eyebrows on one head."
                )
            except Exception as exc:
                print(paint(f"[live chat] reference image rejected: {type(exc).__name__}: {exc}", "error"), flush=True)
                history.append({"role": "assistant", "content": "I couldn't decode that reference image; please upload a JPEG, PNG, or WebP under 24 KB after compression.", "processed_queue_id": str(item.get("id") or ""), "time": datetime.now(timezone.utc).isoformat()})
                save_chat(history)
                save_preview(history)
                return True
        queue_id = str(item.get("id") or "")
        if queue_id and any(h.get("processed_queue_id") == queue_id for h in history):
            return True
        existing_user = next((h for h in history if h.get("queue_id") == queue_id), None) if queue_id else None
        # Never echo website prompt text into the public Actions log.
        print(paint(f"[live chat] received website message ({len(msg)} characters)", "tool"), flush=True)
        if existing_user is None:
            history.append({"role": "user", "content": msg,
                            "time": item.get("createdAt") or datetime.now(timezone.utc).isoformat(),
                            "via": "live", "queue_id": queue_id})
            save_chat(history)
        live_prompt = msg
        finished_live_message = False
        staged_reference_calls: list[dict] = []
        staged_reference_call_keys: set[str] = set()
        reference_calls_released = not bool(reference_path)
        for live_round in range(1, args.rounds + 1):
            label = f"nish-agent live {live_index}.{live_round}"
            try:
                answer2, parsed2 = run_one_round(model, live_prompt, history[:-1], label, True)
            except Exception as exc:
                print(paint(f"[live chat] model call failed: {type(exc).__name__}: {exc}", "error"), flush=True)
                return False
            parsed2 = parsed2 or {}
            thought2 = parsed2.get("thought") or ""
            tool_calls2 = parsed2.get("tool_calls") or []
            answer2 = parsed2.get("answer") or answer2 or ""
            if reference_path and not reference_calls_released:
                for authored_call in tool_calls2:
                    if not isinstance(authored_call, dict):
                        continue
                    call_key = json.dumps(authored_call, ensure_ascii=False, sort_keys=True, default=str)
                    if call_key not in staged_reference_call_keys:
                        staged_reference_call_keys.add(call_key)
                        staged_reference_calls.append(authored_call)
                normalized_calls = [normalize_agent_tool_call(call) for call in staged_reference_calls]
                authored_inspection = any(
                    str(call.get("tool") or "").strip().lower() in ("inspect_image", "read_image")
                    and str(call.get("path") or "") == reference_path
                    for call in normalized_calls
                )
                authored_visual_subagent = any(
                    str(call.get("tool") or "").strip().lower() == "subagent"
                    and bool(str(call.get("instruction") or call.get("prompt") or "").strip())
                    and reference_path in (str(call.get("instruction") or call.get("prompt") or "")
                                           + "\n" + str(call.get("input") or ""))
                    and (call.get("use_tools") is True
                         or str(call.get("use_tools") or "").strip().lower() in ("true", "1", "yes", "on"))
                    for call in normalized_calls
                )
                if not authored_inspection or not authored_visual_subagent:
                    missing = []
                    if not authored_inspection:
                        missing.append(f"inspect_image with path {reference_path}")
                    if not authored_visual_subagent:
                        missing.append(f"subagent with use_tools:true and instruction or input containing {reference_path}")
                    live_prompt = (
                        "Your previous response was rejected. You must author the missing JSON tool call(s) yourself: "
                        + " and ".join(missing)
                        + ". The image is in the workspace at " + reference_path
                        + ". Do not claim another model inspected it; write the call(s) manually now."
                    )
                    print(paint("[live chat] waiting for the local model to author its required visual inspection and sub-agent calls.", "warning"), flush=True)
                    continue
                # Execute only the calls authored by the local model across its retry response(s).
                tool_calls2 = staged_reference_calls
                reference_calls_released = True
            print(paint(f"[agent thought] {thought2[:260]}", "thinking"), flush=True)
            print(paint(f"[agent] {answer2[:500]}", "answer"), flush=True)
            history.append({"role": "assistant", "content": answer2, "thought": thought2,
                            "tool_calls": tool_calls2,
                            "time": datetime.now(timezone.utc).isoformat()})
            save_chat(history)
            if not tool_calls2:
                if queue_id:
                    history[-1]["processed_queue_id"] = queue_id
                finished_live_message = True
                break
            results2 = execute_agent_tools(tool_calls2, label)
            for result in results2:
                history.append({"role": "tool", "tool": result["tool"],
                                "output": result["output"],
                                "time": datetime.now(timezone.utc).isoformat()})
            save_chat(history)
            live_prompt = (
                "Tool results:\n" + json.dumps(results2, ensure_ascii=False, indent=2)[:20000]
                + "\n\nContinue this same task. If done, return no tool_calls and a final answer."
            )
            time.sleep(0.3)
        if queue_id and not finished_live_message:
            failure_note = (
                "I could not author the required image-inspection and tool-enabled sub-agent calls for the supplied reference. "
                "No inspection was fabricated; please resend the image request."
                if reference_path and not reference_calls_released else
                "I reached this message's tool-round limit. The same plan is still active; send a follow-up to continue."
            )
            history.append({"role": "assistant", "content": failure_note,
                            "processed_queue_id": queue_id,
                            "time": datetime.now(timezone.utc).isoformat()})
        save_chat(history)
        save_preview(history)
        return True

    # The current workflow remains the single persistent plan. Website messages
    # are AES-GCM encrypted in a run-scoped Actions variable and read directly
    # through the GitHub API; no Cloudflare or sidecar server is involved.
    try:
        chat_ready = bool(os.environ.get("AGENT_CHAT_REGISTERED") == "true"
                          and os.environ.get("AGENT_CHAT_KEY") and os.environ.get("GITHUB_TOKEN")
                          and os.environ.get("GITHUB_RUN_ID"))
        print(paint("[nish-agent live] persistent plan is active; polling the direct GitHub API for same-run messages.", "success"), flush=True)
        if not chat_ready:
            print(paint("[nish-agent live] no website chat session was attached to this run; continuing as a persistent plan.", "notice"), flush=True)
        last_remote_id = ""
        for live_i in range(600):  # 600*10s = 100m; within the 120m workflow timeout
            if chat_ready:
                try:
                    remote_messages = poll_remote_chat(last_remote_id)
                    for item in remote_messages:
                        message_id = str(item.get("id") or "")
                        if not message_id or message_id <= last_remote_id:
                            continue
                        if not process_live_message(item, live_i + 1):
                            continue
                        last_remote_id = message_id
                        if acknowledge_remote_chat(message_id):
                            print(paint("[live chat] message processed and acknowledged in this run.", "success"), flush=True)
                        save_preview(history)
                except Exception as exc:
                    print(paint(f"[live chat] direct GitHub queue poll failed: {type(exc).__name__}: {exc}", "warning"), flush=True)
            if live_i % 6 == 0:
                print(paint(f"[nish-agent live] heartbeat {live_i}/600 — {len(list(WORKSPACE.rglob('*')))} files — {len(history)} messages — {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC — direct API polling active", "plan"), flush=True)
                save_preview(history)
            time.sleep(10)
        print(paint("[nish-agent live] persistent mode finished — uploading the final chat, tools and workspace artifacts.", "success"), flush=True)
    except Exception as exc:
        print(paint(f"[live] persistent loop ended: {type(exc).__name__}: {exc}", "warning"), flush=True)

    # final summary to step summary
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write("\n## NishAgent — run summary\n\n")
            out.write(f"- **Model:** {model} (preset {preset})\n")
            out.write(f"- **Prompt:** {prompt[:300]}\n")
            out.write(f"- **Rounds:** {len([h for h in history if h.get('role')=='assistant'])}\n")
            out.write(f"- **Workspace:** `dist/agent_workspace` ({len(list(WORKSPACE.rglob('*')))} files)\n")
            out.write(f"- **Chat log:** `dist/agent_chat.json` — {len(history)} messages\n")
            out.write(f"- **Tool log:** `dist/agent_tools.jsonl`\n")

    print(paint("[nish-agent] chat saved to dist/agent_chat.json", "success"), flush=True)
    print(paint("[nish-agent] tools saved to dist/agent_tools.jsonl", "success"), flush=True)
    print(paint("[nish-agent] workspace at dist/agent_workspace — open it in the Vercel explorer", "plan"), flush=True)

if __name__ == "__main__":
    main()
