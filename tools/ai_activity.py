#!/usr/bin/env python3
"""Write safe, structured AI activity records for the Roblox Short dashboard.

The JSONL artifact keeps complete prompts, answers, sub-agent instructions and
file edits. The Actions console gets only a small metadata/preview line so the
live dashboard can filter it from runner commands, package installation and
network chatter. Provider credentials and common token formats are redacted from
both copies; raw provider HTTP request/response bodies are never accepted here.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

DEFAULT_ACTIVITY_PATH = Path("dist/ai_activity.jsonl")
_PRIVATE_FIELDS = {
    "prompt", "messages", "prompt_messages", "input", "output", "text", "response", "thinking", "instruction",
    "context", "file_edits", "tool_calls", "tool_results", "content", "raw",
}
_TOKEN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=?"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(\b(?:api[_-]?key|[A-Z0-9_-]*_API|access[_-]?token|refresh[_-]?token|password|secret)\b[\x22\x27]?\s*[:=]\s*[\x22\x27]?)[^\s,}\x22\x27]{8,}"),
)
_SENSITIVE_KEY_NAMES = {"api_key", "api", "access_token", "refresh_token", "token", "secret", "password", "private_key", "authorization", "credential"}



def _secret_values() -> list[str]:
    values = []
    for name, value in os.environ.items():
        upper = name.upper()
        if (upper in {"BAZAAR_LINK_API", "GEMINI_API_KEY", "GROQ_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"}
                or any(marker in upper for marker in (
                    "API_KEY", "_TOKEN", "TOKEN_", "_SECRET", "SECRET_", "PASSWORD", "PRIVATE_KEY",
                ))):
            candidate = str(value or "").strip()
            # Avoid turning ordinary short test values or single words into
            # unreadable output while still covering real provider credentials.
            if len(candidate) >= 8:
                values.append(candidate)
    return sorted(set(values), key=len, reverse=True)


def redact_secrets(value: Any) -> str:
    """Return a display-safe string with known credentials and token forms masked."""
    text = str(value if value is not None else "")
    for secret in _secret_values():
        text = text.replace(secret, "[REDACTED]")
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) + "[REDACTED]"
                                           if match.lastindex else "[REDACTED]"), text)
    return text


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = key_text.lower().replace("-", "_")
            sensitive = (normalized_key in _SENSITIVE_KEY_NAMES
                         or normalized_key.endswith(("_api", "_api_key", "_token", "_secret",
                                                      "_password", "_private_key", "_authorization",
                                                      "_credential")))
            safe[key_text] = "[REDACTED]" if sensitive and item not in (None, "") else _sanitize(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_secrets(value)


def _compact_preview(event: dict[str, Any], limit: int = 220) -> tuple[str, int] | None:
    for field in ("output", "text", "response", "instruction", "input", "prompt"):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            flat = " ".join(value.split())
            return flat[:limit] + ("…" if len(flat) > limit else ""), len(value)
    return None


def _live_record(record: dict[str, Any]) -> dict[str, Any]:
    """Keep sensitive/long text in the artifact, not the runner's raw log tail."""
    live = {key: value for key, value in record.items() if key not in _PRIVATE_FIELDS}
    preview = _compact_preview(record)
    if preview:
        live["preview"], live["characters"] = preview
    return live


def sanitize_data(value: Any) -> Any:
    """Recursively redact known credentials before writing user-visible artifacts."""
    return _sanitize(value)


def append_activity(event: dict[str, Any], *, path: str | Path | None = None,
                    emit: bool = True, persist: bool = True,
                    live_stream: TextIO | None = None) -> dict[str, Any]:
    """Append a complete safe record; emit only a concise structured live line.

    Failures to write a diagnostic artifact must never stop video generation.
    The caller should pass a run-local path in tests or for a non-default root.
    High-frequency stream telemetry can use ``live_stream=sys.stderr`` so its
    structured records remain available in Actions logs without being inserted
    into the model's human-readable stdout stream.
    """
    record = _sanitize({
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **event,
    })
    if persist:
        target = Path(path) if path else DEFAULT_ACTIVITY_PATH
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            # Activity logging is best-effort and must not fail the user's workflow.
            pass
    if emit:
        try:
            live = _live_record(record)
            print("[ai-log] " + json.dumps(live, ensure_ascii=False, separators=(",", ":")),
                  file=live_stream if live_stream is not None else sys.stdout, flush=True)
        except (OSError, TypeError, ValueError):
            pass
    return record


def parse_live_records(text: str) -> list[dict[str, Any]]:
    """Parse complete ``[ai-log]`` records from a GitHub Actions log tail."""
    records = []
    for line in str(text or "").splitlines():
        marker = "[ai-log] "
        index = line.find(marker)
        if index < 0:
            continue
        try:
            record = json.loads(line[index + len(marker):].strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


if __name__ == "__main__":
    # A small local smoke-test helper without making a provider request.
    event = {"type": "diagnostic", "stage": "test", "status": "ok",
             "output": "Structured AI activity is ready."}
    append_activity(event)
