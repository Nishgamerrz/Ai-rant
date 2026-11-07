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
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import RESET, ansi, paint  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:11434/api/chat"


# A local thinking model can loop on the same paragraph ("let me count again",
# "another attempt:") and burn the whole budget without ever finishing. Any run
# of one sentence repeated back-to-back is treated as a loop.
LOOP_RE = re.compile(r"(\S.{39,400}?)\1{1,}", re.DOTALL)


def looks_stuck(text: str) -> bool:
    """True when the model keeps repeating the same sentence instead of finishing."""
    tail = " ".join(str(text)[-6000:].split())
    return bool(LOOP_RE.search(tail))


CONSOLE_LOCK = threading.Lock()

# The reasoning is printed inside a light frame so it is obviously one block of
# machine thought rather than part of the answer.
#
# The model streams one long paragraph per thought with no line breaks of its
# own, and the log viewer only wraps visually - so a whole paragraph arrived as
# a single log line with the rule at the start and nowhere else. The console now
# breaks the text itself at a modest width, so every visible line begins with the
# rule and the block reads as many lines instead of one endless one.
BOX_WIDTH = 66
BOX_LEFT = "\u2502 "
BOX_TOP = "\u250c\u2500 "
BOX_BOTTOM = "\u2514"

# A model start-up on a CPU runner can take minutes before the first token, and a
# thinking model pauses mid-sentence. One quiet line is useful; a line every
# fifteen seconds buried the model's actual words, so the note is capped.
HEARTBEAT_NOTES = 3


class TypedConsole:
    """Write the live model output one character at a time, in colour.

    The stream used to print whatever chunk Ollama happened to send. A chunk can
    be hundreds of characters, so the console showed text in bursts of whole words
    or whole paragraphs and looked like it "snapped" instead of typing. Writing
    character by character, each flush acting as a single write, makes the log
    build up letter by letter exactly as the model produces it.

    Reasoning and answer are written in different colours (grey vs bright cyan)
    so it is visible at a glance which channel is producing text.

    Pacing is bounded by a per-call budget: after that many seconds the remaining
    characters are written at full speed, so watching the AI type can never delay
    a long run by more than the budget.
    """

    def __init__(self, delay: float = 0.002, budget: float = 120.0, out=None):
        self.delay = max(0.0, float(delay))
        self.budget = max(0.0, float(budget))
        self.spent = 0.0
        self.out = out or sys.stdout
        self.colour = "answer"
        self._open = ""
        self._box = ""
        self._line_start = True
        self._col = 0

    @property
    def pacing(self) -> bool:
        return self.delay > 0 and self.spent < self.budget

    def use(self, kind: str) -> None:
        """Switch the colour for everything written next (thinking vs answer)."""
        if self._box and kind != "thinking":
            with CONSOLE_LOCK:
                self._close_box_locked()
        self.colour = kind

    def _switch(self, kind: str | None = None) -> None:
        wanted = ansi(kind or self.colour, stream=self.out)
        if wanted == self._open:
            return
        if self._open:
            self.out.write(RESET)
        if wanted:
            self.out.write(wanted)
        self._open = wanted

    def write(self, text: str) -> None:
        if not text:
            return
        with CONSOLE_LOCK:
            self._switch()
            for character in text:
                if self._box:
                    if character == "\n":
                        self.out.write("\n")
                        self._line_start = True
                        self._col = 0
                        continue
                    if self._line_start:
                        self.out.write(BOX_LEFT)
                        self._line_start = False
                        self._col = len(BOX_LEFT)
                    # Wrap on the first space after the width is reached. Breaking
                    # mid-word would look like a typo, so a line may run one word
                    # over instead.
                    if self._col >= self._width() and character in " \t":
                        self.out.write("\n")
                        self._line_start = True
                        self._col = 0
                        continue
                    self.out.write(character)
                    self._col += 1
                else:
                    self.out.write(character)
                    self._line_start = character == "\n"
                self.out.flush()
                if self.pacing:
                    time.sleep(self.delay)
                    self.spent += self.delay

    def line(self, text: str = "", kind: str = "") -> None:
        with CONSOLE_LOCK:
            self._close_box_locked()
            if self._open:
                self.out.write(RESET)
                self._open = ""
            if kind:
                text = paint(text, kind, stream=self.out)
            self.out.write(text + "\n")
            self.out.flush()
            self._line_start = True
            self._col = 0

    def newline(self) -> None:
        self.line("")

    # -- the framed reasoning pane ---------------------------------------
    def _width(self) -> int:
        return BOX_WIDTH

    def _frame(self, text: str) -> None:
        """Write one border line in the near-invisible frame colour."""
        self.out.write(RESET + paint(text, "frame", stream=self.out) + "\n")
        self.out.flush()
        self._open = ""

    def _close_box_locked(self) -> None:
        if not self._box:
            return
        if not self._line_start:
            self.out.write("\n")
        head = BOX_BOTTOM
        self._frame(head + "\u2500" * max(0, BOX_WIDTH - len(head)))
        self._box = ""
        self._line_start = True

    def open_box(self, title: str = "thinking") -> None:
        """Start a framed panel: everything written next is boxed until switched."""
        with CONSOLE_LOCK:
            if self._box:
                return
            if not self._line_start:
                self.out.write("\n")
            self._box = title or "thinking"
            head = BOX_TOP + self._box + " "
            self._frame(head + "\u2500" * max(0, BOX_WIDTH - len(head)))
            self._line_start = True

    def close_box(self) -> None:
        with CONSOLE_LOCK:
            self._close_box_locked()

    def note(self, text: str, kind: str = "thought") -> None:
        """One-off note that stays inside the frame instead of breaking it."""
        with CONSOLE_LOCK:
            if not self._line_start:
                self.out.write("\n")
            rule = paint(BOX_LEFT, "frame", stream=self.out) if self._box else ""
            self.out.write(RESET + rule + paint(text, kind, stream=self.out) + "\n")
            self.out.flush()
            self._open = ""
            self._line_start = True
            self._col = 0


class Heartbeat(threading.Thread):
    """A very quiet "still working" note so the log never looks frozen.

    A CPU runner can spend minutes loading a model before the first token. The
    old timer printed a line every fifteen seconds for the whole wait, which
    buried the model's own words in repetition. This one writes at most
    `HEARTBEAT_NOTES` notes per call, in the darkest colour on the palette, and
    says in the line itself that it is a quiet note so it is clearly not output.
    """

    def __init__(self, label: str, interval: float, console: TypedConsole,
                 limit: int = HEARTBEAT_NOTES):
        super().__init__(daemon=True)
        self.label = label
        self.interval = max(2.0, float(interval))
        self.console = console
        self.limit = max(1, int(limit))
        self.state = "waiting for the first token"
        self.activity = time.time()
        self.started = self.activity
        # Not _stop: Thread already has a private _stop() method.
        self._finished = threading.Event()
        self.messages = 0

    def touch(self, state: str | None = None) -> None:
        self.activity = time.time()
        if state:
            self.state = state

    def stop(self) -> None:
        self._finished.set()

    def run(self) -> None:
        while not self._finished.wait(min(5.0, self.interval)):
            if self.messages >= self.limit:
                return
            idle = time.time() - self.activity
            if idle < self.interval:
                continue
            if self.state == "waiting for the first token":
                text = (f"[{self.label}] still loading the model: "
                        f"{time.time() - self.started:.0f}s so far")
            else:
                text = f"[{self.label}] nothing new for {idle:.0f}s, still working"
            self.console.note(f"{text} (quiet note {self.messages + 1}/{self.limit})")
            self.messages += 1
            self.activity = time.time()
            if self.messages >= self.limit:
                return


class ThinkingUnsupported(Exception):
    """Raised when the selected model has no reasoning channel at all."""


class ModelUnusable(Exception):
    """Raised when Ollama fails (5xx) to load or run the selected model."""


class ModelTooSlow(Exception):
    """Raised when a preset is so slow that the run would miss its budget.

    A 14B model on a CPU runner can spend 20+ minutes on one narration request.
    The workflow gives each call a wall-clock allowance; when it runs out this
    exception triggers the fallback ladder instead of blocking the whole run.
    """


def stream(request: dict, url: str, label: str, timeout: float, quiet: bool,
           max_seconds: float = 0.0, stall_seconds: float = 0.0,
           type_delay: float = 0.002, type_budget: float = 120.0,
           heartbeat_seconds: float = 15.0) -> dict:
    request = {**request, "stream": True}
    payload = json.dumps(request).encode("utf-8")
    http = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    content: list[str] = []
    thinking: list[str] = []
    console = TypedConsole(type_delay, type_budget)
    beat = None if quiet or heartbeat_seconds <= 0 else Heartbeat(label, heartbeat_seconds, console)
    if beat:
        beat.start()
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
    last_progress = time.time()
    started_at = last_progress
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
            if beat and (piece_thinking or piece_content):
                beat.touch("streaming the answer" if piece_content else "streaming its reasoning")
            if piece_thinking:
                thinking.append(piece_thinking)
                if not quiet:
                    if not thinking_open:
                        if beat:
                            beat.touch()
                        console.use("thinking")
                        console.open_box(f"[{label}] thinking")
                        thinking_open = True
                    console.write(piece_thinking)
            if piece_content:
                content.append(piece_content)
                if not quiet:
                    if not answer_open:
                        console.use("answer")   # leaving the reasoning colour closes the box
                        console.write(f"[{label}] answer \u25b8 ")
                        answer_open = True
                    console.write(piece_content)
            # Watch the reasoning channel while it streams: that is where a local
            # model loops ("let me count again", "another attempt:"). The answer is
            # only checked at the end, so a legitimate list of similar JSON objects
            # in a world plan is never mistaken for a loop.
            if not repeated and piece_thinking:
                seen += len(piece_thinking)
                if seen > 1200 and looks_stuck("".join(thinking)):
                    repeated = True
                    if not quiet:
                        console.close_box()
                        console.line(
                            f"[{label}] the model is looping on the same words instead of "
                            f"finishing; telling it to stop repeating and write the answer once.",
                            kind="warning")
            if piece_thinking or piece_content:
                last_progress = time.time()
            now = time.time()
            if max_seconds and now - started_at > max_seconds:
                console.close_box()
                raise ModelTooSlow(
                    f"still going after {now - started_at:.0f}s "
                    f"(budget {max_seconds:.0f}s); handing this call to the faster model")
            if stall_seconds and now - last_progress > stall_seconds:
                console.close_box()
                raise ModelTooSlow(
                    f"no output for {stall_seconds:.0f}s; handing this call to the faster model")
            if event.get("done"):
                tokens = int(event.get("eval_count") or 0)
                done_reason = str(event.get("done_reason") or "")
    if beat:
        beat.stop()
    answer = "".join(content)
    reasoning = "".join(thinking)
    if not repeated and done_reason == "length" and looks_stuck(answer):
        repeated = True
        if not quiet:
            print(paint(f"[{label}] the answer itself is repeating and was cut off; "
                  f"it will be finished with a steering instruction.", "warning"), flush=True)
    elapsed = time.time() - started
    if not quiet:
        console.close_box()
        rate = f", {tokens / elapsed:.1f} tok/s" if elapsed >= 1 and tokens else ""
        console.line(f"[{label}] \u2713 finished in {elapsed:.0f}s: {len(answer):,} answer chars, "
                     f"{len(reasoning):,} reasoning chars, {tokens} tokens{rate}"
                     f"{', CUT OFF at the token ceiling' if done_reason == 'length' else ''}.",
                     kind="error" if done_reason == "length" else "success")
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
    parser.add_argument("--fallback-thinking", default="true",
                        help="whether the fallback model should use thinking (default true)")
    parser.add_argument("--max-seconds", type=float, default=0.0,
                        help="wall-clock allowance for this call; 0 = no limit")
    parser.add_argument("--stall-seconds", type=float, default=0.0,
                        help="give up if the model emits nothing for this long; 0 = no limit")
    parser.add_argument("--type-delay", type=float,
                        default=float(os.environ.get("AI_TYPE_DELAY", "0.002")),
                        help="seconds to pause between printed characters; 0 prints at full "
                             "speed (default 2 ms per character, so the log visibly types)")
    parser.add_argument("--type-budget", type=float,
                        default=float(os.environ.get("AI_TYPE_BUDGET", "120")),
                        help="most seconds the typing pace may add to one call "
                             "(after that the text is written at full speed)")
    parser.add_argument("--heartbeat-seconds", type=float,
                        default=float(os.environ.get("AI_HEARTBEAT", "60")),
                        help="print one quiet 'still working' note when nothing has "
                             "arrived for this long (at most 3 per call); 0 disables it")
    parser.add_argument("--keep-stream-flag", action="store_true",
                        help="keep stream:true in the written request file for debugging")
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    model = request.get("model", "model")
    thinking_on = bool(request.get("think"))
    print(paint(f"[{args.label}] sending {model} request "
                f"(temperature {request.get('options', {}).get('temperature', 'default')}, "
                f"thinking {'on' if thinking_on else 'off'}); live thinking is printed below.",
                "label"), flush=True)
    quiet_note = ("" if args.heartbeat_seconds <= 0 else
                  f" If it goes quiet you get at most {HEARTBEAT_NOTES} short notes, "
                  f"{int(args.heartbeat_seconds)}s apart; no repeated chatter.")
    print(paint(f"[{args.label}] \u25b8 streaming live: the model's reasoning then its answer "
                f"will appear here letter by letter as it produces them, reasoning in a "
                f"framed box.{quiet_note}", "notice"), flush=True)

    limits = {"max_seconds": args.max_seconds, "stall_seconds": args.stall_seconds,
              "type_delay": args.type_delay, "type_budget": args.type_budget,
              "heartbeat_seconds": args.heartbeat_seconds}

    def run_once(payload: dict, note: str) -> dict:
        result = stream(payload, args.url, args.label, args.timeout, args.quiet, **limits)
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
                print(paint(f"[{args.label}] the model hit its {ceiling}-token ceiling and "
                            f"was cut off{note}; asking again with num_predict={bigger} and "
                            f"thinking still on.", "warning"), flush=True)
            elif looping and bigger > ceiling:
                print(paint(f"[{args.label}] re-sending with num_predict={bigger} and an "
                            f"explicit instruction to stop repeating itself.", "warning"),
                      flush=True)
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
            retried = stream(retry_payload, args.url, args.label, args.timeout, args.quiet, **limits)
            retried["token_ceiling_retry"] = bigger
            retried["steered_after_repeat"] = looping
            if retried.get("done_reason") != "length" and not retried.get("repeated"):
                return retried
            print(paint(f"[{args.label}] still stuck at num_predict={bigger}; keeping the "
                        f"longest answer. Shorten the reasoning instructions or raise the "
                        f"preset budget.", "warning"), flush=True)
            if len(retried.get("response") or "") >= len(result.get("response") or ""):
                result = retried
        return result

    def attempt(payload: dict, note: str = "") -> dict | None:
        try:
            return run_once(payload, note)
        except ThinkingUnsupported as exc:
            # Thinking is requested for every preset, but a few architectures
            # have no reasoning channel. Answer normally instead of failing.
            print(paint(f"[{args.label}] this model has no thinking channel ({exc}); "
                        f"answering without reasoning tokens.{note}", "warning"), flush=True)
            try:
                result = run_once({**payload, "think": False}, note)
            except (ModelUnusable, ThinkingUnsupported) as retry_exc:
                print(paint(f"[{args.label}] the model is unusable at all ({retry_exc}).",
                            "error"), flush=True)
                return None
            result["thinking_unsupported"] = True
            return result
        except ModelTooSlow as exc:
            print(paint(f"[{args.label}] {model} is too slow for this run ({exc}).",
                        "warning"), flush=True)
            return None
        except ModelUnusable as exc:
            print(paint(f"[{args.label}] {model} cannot run here ({exc}).", "error"),
                  flush=True)
            return None

    try:
        result = attempt(request)
        if result is None and args.fallback_model and args.fallback_model != model:
            print(paint(f"[{args.label}] switching to the known-good fallback model "
                        f"{args.fallback_model} so the run continues.", "warning"), flush=True)
            fallback = {**request, "model": args.fallback_model,
                        "think": bool(args.fallback_thinking)}
            result = attempt(fallback, f" (fallback {args.fallback_model})")
            if result is not None:
                result["fallback_model"] = args.fallback_model
        if result is None:
            raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(paint(f"[{args.label}] streaming request failed: {type(exc).__name__}: {exc}",
                    "error"), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    if not result["response"].strip():
        print(paint(f"[{args.label}] the model returned an empty answer.", "error"),
              file=sys.stderr, flush=True)
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
