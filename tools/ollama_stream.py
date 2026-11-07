#!/usr/bin/env python3
"""Stream an Ollama chat request and show the model's live thinking in the log.

The workflow used to post a blocking request, so the Actions console sat silent
for minutes while the model worked. This wrapper asks Ollama to stream, prints
the reasoning and the answer as they arrive, and finally writes the same
aggregated JSON envelope the rest of the pipeline already reads.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:11434/api/chat"


# A local thinking model can loop on the same paragraph ("let me count again",
# "another attempt:") and burn the whole budget without ever finishing. Any run
# of one sentence repeated back-to-back is treated as a loop.
LOOP_RE = re.compile(r"(\S.{39,400}?)\1{1,}", re.DOTALL)


def looks_stuck(text: str) -> bool:
    """True when the model keeps repeating the same sentence instead of finishing."""
    tail = " ".join(str(text)[-6000:].split())
    return bool(LOOP_RE.search(tail))


class ThinkingUnsupported(Exception):
    """Raised when the selected model has no reasoning channel at all."""


class ModelUnusable(Exception):
    """Raised when Ollama fails (5xx) to load or run the selected model."""


def stream(request: dict, url: str, label: str, timeout: float, quiet: bool) -> dict:
    request = {**request, "stream": True}
    payload = json.dumps(request).encode("utf-8")
    http = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    content: list[str] = []
    thinking: list[str] = []
    started = time.time()
    tokens = 0
    done_reason = ""
    # Live console: every streamed piece is printed verbatim the moment it
    # arrives, so the log fills in letter by letter. The old code reprinted a
    # truncated "thinking... 2,117 chars, 333s - ...tail" line every two seconds,
    # which looked like the text was being replaced instead of streamed.
    thinking_open = False
    answer_open = False
    repeated = False
    seen = 0
    try:
        handle = urllib.request.urlopen(http, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 400 and "think" in detail.lower():
            raise ThinkingUnsupported(detail.strip()[:300]) from exc
        if exc.code >= 500:
            # For example llama3.2-vision: Ollama exits with
            # "unknown model architecture: 'mllama'" and returns HTTP 500.
            raise ModelUnusable(f"HTTP {exc.code}: {detail.strip()[:300]}") from exc
        raise
    with handle as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = event.get("message") or {}
            piece_thinking = message.get("thinking") or ""
            piece_content = message.get("content") or ""
            if piece_thinking:
                thinking.append(piece_thinking)
                if not quiet:
                    if not thinking_open:
                        print(f"[{label}] thinking \u25b8 ", end="", flush=True)
                        thinking_open = True
                    print(piece_thinking, end="", flush=True)
            if piece_content:
                content.append(piece_content)
                if not quiet:
                    if not answer_open:
                        if thinking_open:
                            print(flush=True)
                        print(f"[{label}] answer \u25b8 ", end="", flush=True)
                        answer_open = True
                    print(piece_content, end="", flush=True)
            # Watch the reasoning channel while it streams: that is where a local
            # model loops ("let me count again", "another attempt:"). The answer is
            # only checked at the end, so a legitimate list of similar JSON objects
            # in a world plan is never mistaken for a loop.
            if not repeated and piece_thinking:
                seen += len(piece_thinking)
                if seen > 1200 and looks_stuck("".join(thinking)):
                    repeated = True
                    if not quiet:
                        if answer_open or thinking_open:
                            print(flush=True)
                        print(f"[{label}] the model is looping on the same words instead of "
                              f"finishing; telling it to stop repeating and write the answer once.",
                              flush=True)
            if event.get("done"):
                tokens = int(event.get("eval_count") or 0)
                done_reason = str(event.get("done_reason") or "")
    answer = "".join(content)
    reasoning = "".join(thinking)
    if not repeated and done_reason == "length" and looks_stuck(answer):
        repeated = True
        if not quiet:
            print(f"[{label}] the answer itself is repeating and was cut off; "
                  f"it will be finished with a steering instruction.", flush=True)
    elapsed = time.time() - started
    if not quiet:
        if answer_open or thinking_open:
            print(flush=True)
        rate = f", {tokens / elapsed:.1f} tok/s" if elapsed >= 1 and tokens else ""
        print(f"[{label}] \u2713 finished in {elapsed:.0f}s: {len(answer):,} answer chars, "
              f"{len(reasoning):,} reasoning chars, {tokens} tokens{rate}"
              f"{', CUT OFF at the token ceiling' if done_reason == 'length' else ''}.", flush=True)
    return {
        "message": {"role": "assistant", "content": answer, "thinking": reasoning},
        "response": answer,
        "thinking": reasoning,
        "done": True,
        "eval_count": tokens,
        "done_reason": done_reason,
        "truncated": done_reason == "length",
        "repeated": repeated,
        "label": label,
        "elapsed_seconds": round(elapsed, 1),
    }


MAX_PREDICT_CEILING = 16384


def next_token_budget(current: int) -> int:
    """Double the ceiling, with a floor that fits a full story and its reasoning."""
    return min(MAX_PREDICT_CEILING, max(int(current) * 2, 4096))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="Ollama chat request JSON")
    parser.add_argument("--output", required=True, type=Path, help="where to write the aggregated response")
    parser.add_argument("--label", default="AI", help="console prefix, e.g. 'world plan'")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--fallback-model", default="",
                        help="known-good model to retry on when the selected one cannot run")
    parser.add_argument("--fallback-thinking", default="false",
                        help="whether the fallback model should use thinking (default false)")
    parser.add_argument("--keep-stream-flag", action="store_true",
                        help="keep stream:true in the written request file for debugging")
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    model = request.get("model", "model")
    thinking_on = bool(request.get("think"))
    print(f"[{args.label}] sending {model} request "
          f"(temperature {request.get('options', {}).get('temperature', 'default')}, "
          f"thinking {'on' if thinking_on else 'off'}); live thinking is printed below.", flush=True)

    def run_once(payload: dict, note: str) -> dict:
        result = stream(payload, args.url, args.label, args.timeout, args.quiet)
        # A reasoning model can spend the whole num_predict budget thinking and
        # stop mid-sentence (`done_reason: "length"`). That used to surface as a
        # mysteriously short story and burn a whole retry round; finish it here
        # by repeating the same request with a larger ceiling.
        ceiling = int((payload.get("options") or {}).get("num_predict") or 0)
        cut_off = result.get("done_reason") == "length"
        looping = bool(result.get("repeated"))
        if (cut_off or looping) and ceiling:
            bigger = next_token_budget(ceiling)
            if cut_off and bigger > ceiling:
                print(f"[{args.label}] the model hit its {ceiling}-token ceiling and was cut off{note}; "
                      f"asking again with num_predict={bigger} and thinking still on.", flush=True)
            elif looping and bigger > ceiling:
                print(f"[{args.label}] re-sending with num_predict={bigger} and an explicit "
                      f"instruction to stop repeating itself.", flush=True)
            else:
                return result
            # Thinking stays ON for every retry: the user chose to watch the model
            # reason every time. The steering message is what stops it looping --
            # it is told plainly that it was repeating and must write the complete
            # answer once instead of starting another draft.
            steer = (
                "You were repeating yourself and running out of room. Do NOT restate the "
                "plan, do NOT count words again, and do NOT start another draft. "
                "Write the final, complete answer now, in one pass."
                if looping else
                "Your previous answer was cut off before it finished. Continue and write the "
                "final, complete answer now, in one pass."
            )
            retry_payload = {
                **payload,
                "messages": [*(payload.get("messages") or []),
                             {"role": "user", "content": steer}],
                "options": {**(payload.get("options") or {}), "num_predict": bigger},
            }
            retried = stream(retry_payload, args.url, args.label, args.timeout, args.quiet)
            retried["token_ceiling_retry"] = bigger
            retried["steered_after_repeat"] = looping
            if retried.get("done_reason") != "length" and not retried.get("repeated"):
                return retried
            print(f"[{args.label}] still stuck at num_predict={bigger}; keeping the longest answer. "
                  f"Shorten the reasoning instructions or raise the preset budget.", flush=True)
            if len(retried.get("response") or "") >= len(result.get("response") or ""):
                result = retried
        return result

    def attempt(payload: dict, note: str = "") -> dict | None:
        try:
            return run_once(payload, note)
        except ThinkingUnsupported as exc:
            # Thinking is requested for every preset, but a few architectures
            # have no reasoning channel. Answer normally instead of failing.
            print(f"[{args.label}] this model has no thinking channel ({exc}); "
                  f"answering without reasoning tokens.{note}", flush=True)
            try:
                result = run_once({**payload, "think": False}, note)
            except (ModelUnusable, ThinkingUnsupported) as retry_exc:
                print(f"[{args.label}] the model is unusable at all ({retry_exc}).", flush=True)
                return None
            result["thinking_unsupported"] = True
            return result
        except ModelUnusable as exc:
            print(f"[{args.label}] {model} cannot run here ({exc}).", flush=True)
            return None

    try:
        result = attempt(request)
        if result is None and args.fallback_model and args.fallback_model != model:
            print(f"[{args.label}] switching to the known-good fallback model "
                  f"{args.fallback_model} so the run continues.", flush=True)
            fallback = {**request, "model": args.fallback_model,
                        "think": bool(args.fallback_thinking)}
            result = attempt(fallback, f" (fallback {args.fallback_model})")
            if result is not None:
                result["fallback_model"] = args.fallback_model
        if result is None:
            raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[{args.label}] streaming request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not result["response"].strip():
        print(f"[{args.label}] the model returned an empty answer.", file=sys.stderr)
        raise SystemExit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result["model"] = request.get("model") if "fallback_model" not in result else result["fallback_model"]
    args.output.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(f"- **{args.label}:** {result['eval_count']} tokens in {result['elapsed_seconds']}s "
                      f"({len(result['response']):,} answer chars)\n")


if __name__ == "__main__":
    main()
