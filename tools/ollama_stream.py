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
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import RESET, ansi, paint  # noqa: E402
from ai_activity import append_activity  # noqa: E402

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
                 limit: int = HEARTBEAT_NOTES, resident: bool | None = None,
                 prompt_chars: int = 0):
        super().__init__(daemon=True)
        self.label = label
        # True/False when /api/ps answered, None when it could not be asked.
        self.resident = resident
        self.prompt_chars = prompt_chars
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
        while not self._finished.wait(self.interval):
            if self.messages >= self.limit:
                return
            idle = time.time() - self.activity
            if idle < self.interval - 0.05:
                continue
            if self.state == "waiting for the first token":
                if self.resident is True:
                    text = f"[{self.label}] already in memory, no reload — reading {self.prompt_chars:,}-character plan prompt"
                elif self.resident is False:
                    text = f"[{self.label}] still loading the model into memory"
                else:
                    text = f"[{self.label}] no first token yet"
            else:
                text = f"[{self.label}] still working {idle:.0f}s"
            self.console.note(f"{text} (quiet note {self.messages + 1}/{self.limit})")
            self.messages += 1
            self.activity = time.time()
            if self.messages >= self.limit:
                return


class ThinkingUnsupported(Exception):
    """Raised when the selected model has no reasoning channel at all."""


class ModelMissing(Exception):
    """The model named in the request is not installed on this runner."""


def installed_models(url: str, timeout: float = 30) -> set[str]:
    """Names Ollama reports in /api/tags, as 'name:tag'.

    Asked before a hand-over: switching to a model that is not on disk is not a
    rescue, it is a 404 that loses the call.
    """
    base = url.split("/api/")[0]
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as handle:
            payload = json.loads(handle.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - never let the probe itself break a call
        return set()
    names = set()
    for entry in payload.get("models") or []:
        name = str(entry.get("name") or entry.get("model") or "")
        if name:
            names.add(name)
            if ":" not in name:
                names.add(f"{name}:latest")
    return names


def resident_models(url: str, timeout: float = 10) -> set[str]:
    """Names Ollama currently holds IN MEMORY (/api/ps), as 'name:tag'.

    This answers the question the console used to guess at: a long silence before
    the first token is NOT always a load. When the model is already resident the
    wait is prompt prefill (a 6,000-token blueprint prompt takes minutes on a CPU
    runner), and saying "still loading the model" made a normal step look like a
    reload.
    """
    base = url.split("/api/")[0]
    try:
        with urllib.request.urlopen(f"{base}/api/ps", timeout=timeout) as handle:
            payload = json.loads(handle.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - a probe must never break a call
        return set()
    names = set()
    for entry in payload.get("models") or []:
        name = str(entry.get("name") or entry.get("model") or "")
        if name:
            names.add(name)
            if ":" not in name:
                names.add(f"{name}:latest")
    return names


def is_resident(model: str, url: str) -> bool:
    wanted = model.strip()
    wanted = wanted if ":" in wanted else f"{wanted}:latest"
    return wanted in resident_models(url)


class ModelUnusable(Exception):
    """Raised when Ollama fails (5xx) to load or run the selected model."""


class NoOutputStall(Exception):
    """Raised only when no thinking or answer content arrives for the stall window."""


def stream(request: dict, url: str, label: str, timeout: float, quiet: bool,
           stall_seconds: float = 0.0,
           type_delay: float = 0.002, type_budget: float = 120.0,
           heartbeat_seconds: float = 15.0) -> dict:
    request = {**request, "stream": True}
    payload = json.dumps(request).encode("utf-8")
    http = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    content: list[str] = []
    thinking: list[str] = []
    console = TypedConsole(type_delay, type_budget)
    # Ask Ollama whether these weights are already in RAM, so a long wait is
    # described correctly: a real load, or prompt prefill on a resident model.
    model_name = str(request.get("model") or "")
    resident = is_resident(model_name, url) if model_name else None
    prompt_chars = sum(len(str(message.get("content") or ""))
                       for message in (request.get("messages") or []))
    if not quiet and model_name:
        if resident:
            print(paint(f"[{label}] {model_name} in memory — reading {prompt_chars:,}-char prompt", "notice"), flush=True)
        elif resident is False:
            print(paint(f"[{label}] {model_name} loading (first load)", "warning"), flush=True)
    beat = None if quiet or heartbeat_seconds <= 0 else Heartbeat(
        label, heartbeat_seconds, console, resident=resident, prompt_chars=prompt_chars)
    if beat:
        beat.start()
    started = time.monotonic()
    started_at = started
    tokens = 0
    prompt_tokens = 0
    prompt_ns = 0
    done_reason = ""
    # Live console: every streamed piece is printed verbatim the moment it
    # arrives, so the log fills in letter by letter. The old code reprinted a
    # truncated "thinking... 2,117 chars, 333s - ...tail" line every two seconds,
    # which looked like the text was being replaced instead of streamed.
    thinking_open = False
    answer_open = False
    repeated = False
    seen = 0
    last_progress = started_at
    first_output = 0.0
    activity_id = f"{os.getpid()}-{time.time_ns()}"
    progress_chars = {"thinking": 0, "answer": 0}
    last_activity_channel = ""
    last_activity_emit = 0.0

    def emit_activity_progress(channel: str, *, force: bool = False) -> None:
        nonlocal last_activity_channel, last_activity_emit
        accumulated = "".join(thinking if channel == "thinking" else content)
        now = time.monotonic()
        if not accumulated:
            return
        if (not force and len(accumulated) - progress_chars[channel] < 240
                and channel == last_activity_channel and now - last_activity_emit < 5):
            return
        progress_chars[channel] = len(accumulated)
        last_activity_channel = channel
        last_activity_emit = now
        preview = " ".join(accumulated.split())[-200:]
        # Keep structured progress in the uploaded activity artifact. The live
        # thinking/answer text is already streamed below; do not inject JSON logs
        # into the Actions console or the user's readable model output.
        append_activity({
            "type": "model_progress", "stage": "ollama",
            "activity_id": activity_id, "tag": f"[{label} AI]", "label": label,
            "provider": "ollama", "model": model_name, "status": "streaming",
            "channel": channel, "preview": preview, "characters": len(accumulated),
        }, path=Path("dist/ai_activity.jsonl"), emit=False)

    def hand_off_if_silent_timeout(exc: BaseException) -> None:
        """Turn an idle socket timeout into a hand-off only after the stall window."""
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        if not stall_seconds or not isinstance(reason, (TimeoutError, socket.timeout)):
            return
        idle = time.monotonic() - last_progress
        if idle >= stall_seconds:
            console.close_box()
            raise NoOutputStall(
                f"no thinking or answer output for {idle:.0f}s "
                f"(stall window {stall_seconds:.0f}s); handing this call to the fallback model") from exc

    def response_lines(response):
        """Read lines while making a truly silent stream observable."""
        try:
            yield from response
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            hand_off_if_silent_timeout(exc)
            raise
        finally:
            if beat:
                beat.stop()

    # urllib's timeout is an idle-socket timeout, not a total call deadline.
    # Limit an idle read to the configured stall window so a model that never
    # emits a first token (or goes silent mid-thought) can be handed off on time.
    request_timeout = (min(timeout, stall_seconds)
                       if stall_seconds > 0 and timeout > 0 else timeout)
    try:
        handle = urllib.request.urlopen(http, timeout=request_timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if beat:
            beat.stop()
        if exc.code == 400 and "think" in detail.lower():
            raise ThinkingUnsupported(detail.strip()[:300]) from exc
        if exc.code == 404:
            # Ollama answers 404 for a model it does not have ("model 'qwen3:4b' not
            # found"). This used to escape as a bare HTTPError and kill the whole
            # call - the world plan died that way when the fallback had never been
            # pulled, and the run silently produced a procedural world instead of the
            # AI's furnished one.
            raise ModelMissing(f"HTTP 404: {detail.strip()[:300]}") from exc
        if exc.code >= 500:
            # For example llama3.2-vision: Ollama exits with
            # "unknown model architecture: 'mllama'" and returns HTTP 500.
            raise ModelUnusable(f"HTTP {exc.code}: {detail.strip()[:300]}") from exc
        raise
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        try:
            hand_off_if_silent_timeout(exc)
        finally:
            if beat:
                beat.stop()
        raise
    with handle as response:
        for raw in response_lines(response):
            now = time.monotonic()
            idle = now - last_progress
            if stall_seconds and idle >= stall_seconds:
                console.close_box()
                raise NoOutputStall(
                    f"no thinking or answer output for {idle:.0f}s "
                    f"(stall window {stall_seconds:.0f}s); handing this call to the fallback model")
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
                emit_activity_progress("thinking")
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
                emit_activity_progress("answer")
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
                last_progress = time.monotonic()
                if not first_output:
                    first_output = last_progress
            if event.get("done"):
                tokens = int(event.get("eval_count") or 0)
                done_reason = str(event.get("done_reason") or "")
                prompt_tokens = int(event.get("prompt_eval_count") or 0)
                prompt_ns = int(event.get("prompt_eval_duration") or 0)
    if beat:
        beat.stop()
    if thinking:
        emit_activity_progress("thinking", force=True)
    if content:
        emit_activity_progress("answer", force=True)
    answer = "".join(content)
    reasoning = "".join(thinking)
    if not repeated and done_reason == "length" and looks_stuck(answer):
        repeated = True
        if not quiet:
            print(paint(f"[{label}] the answer itself is repeating and was cut off; "
                  f"it will be finished with a steering instruction.", "warning"), flush=True)
    elapsed = time.monotonic() - started
    # How long this call waited before it produced its first character. If the model
    # is already in RAM this is prompt processing only, a second or two; if it had to
    # be loaded from disk it is tens of seconds. Printing it makes a reload visible
    # instead of something the user has to guess at, and it is what the next step's
    # speed depends on.
    first_char_seconds = round((first_output - started_at), 1) if first_output else None
    if not quiet:
        console.close_box()
        rate = f", {tokens / elapsed:.1f} tok/s" if elapsed >= 1 and tokens else ""
        prefill = (f", it read {prompt_tokens:,} prompt tokens in "
                   f"{prompt_ns / 1e9:.0f}s first" if prompt_tokens and prompt_ns else "")
        if first_char_seconds is not None:
            if first_char_seconds >= 15 and not resident:
                console.line(f"[{label}] the first word took {first_char_seconds:.0f}s: the "
                             f"weights were NOT in memory, so this call loaded "
                             f"{model_name} first{prefill}.", kind="warning")
            elif first_char_seconds >= 15:
                console.line(f"[{label}] first word after {first_char_seconds:.0f}s - no "
                             f"reload: {model_name} was already in memory, that was prompt "
                             f"reading{prefill}.", kind="success")
            else:
                console.line(f"[{label}] first word after {first_char_seconds:.0f}s "
                             f"(no reload: the weights were already in memory){prefill}.",
                             kind="success")
        console.line(f"[{label}] \u2713 finished in {elapsed:.0f}s: {len(answer):,} answer chars, "
                     f"{len(reasoning):,} reasoning chars, {tokens} tokens{rate}"
                     f"{', CUT OFF at the token ceiling' if done_reason == 'length' else ''}.",
                     kind="error" if done_reason == "length" else "success")
    return {
        "activity_id": activity_id,
        "message": {"role": "assistant", "content": answer, "thinking": reasoning},
        "response": answer,
        "thinking": reasoning,
        "prompt_eval_count": prompt_tokens,
        "prompt_eval_seconds": round(prompt_ns / 1e9, 1) if prompt_ns else None,
        "model_was_resident": resident,
        "done": True,
        "eval_count": tokens,
        "done_reason": done_reason,
        "truncated": done_reason == "length",
        "repeated": repeated,
        "label": label,
        "elapsed_seconds": round(elapsed, 1),
        "first_char_seconds": first_char_seconds,
    }


MAX_PREDICT_CEILING = 16384


def next_token_budget(current: int) -> int:
    """Double the ceiling, with a floor that fits a full story and its reasoning."""
    return min(MAX_PREDICT_CEILING, max(int(current) * 2, 4096))


def stick_to_fallback(model: str, label: str, state_path: Path | None = None) -> None:
    """Tell the rest of the workflow to keep using `model` from now on.

    Written through GITHUB_ENV so later steps see it, and applied to this process
    too. Every later call in the run names the run's primary model, so without
    this the next call reloads the slow model (minutes), finds it slow again, then
    reloads the fallback: a reload before every step. Nothing happens when
    GITHUB_ENV is absent, which keeps local runs unchanged.
    """
    os.environ["AI_MODEL"] = model
    os.environ["AI_MODEL_STICKY"] = "1"
    if state_path is not None:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(model + "\n", encoding="utf-8")
        except OSError:
            pass
    target = os.environ.get("GITHUB_ENV")
    print(paint(f"[{label}] {model} is now this run's model, so the remaining steps "
                "think on the weights already in memory instead of reloading "
                "between steps.", "plan"), flush=True)
    if not target:
        return
    try:
        with Path(target).open("a", encoding="utf-8") as out:
            out.write(f"AI_MODEL={model}\n")
            out.write("AI_MODEL_STICKY=1\n")
    except OSError:
        return


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
    parser.add_argument("--stall-seconds", type=float, default=0.0,
                        help="hand off only if no thinking or answer content arrives for this "
                             "long; 0 = no limit")
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
    # One model resident for the whole run. The state file sits next to the output
    # so every call in this run - including a second attempt inside the same step,
    # where GITHUB_ENV has already been read for the last time - is rewritten to the
    # model that is actually loaded. That is what stops the reload-per-step cycle.
    state_path = args.output.parent / ".ai_model"
    if state_path.is_file():
        resident = state_path.read_text(encoding="utf-8").strip()
        if resident and resident != request.get("model"):
            print(paint(f"[{args.label}] {resident} is already loaded for this run, so this "
                        f"call uses it instead of reloading {request.get('model')}.",
                        "notice"), flush=True)
            request["model"] = resident
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

    limits = {"stall_seconds": args.stall_seconds,
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
            retried = stream(retry_payload, args.url, args.label, args.timeout, args.quiet,
                             **limits)
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
            except (ModelUnusable, ModelMissing, ThinkingUnsupported) as retry_exc:
                print(paint(f"[{args.label}] the model is unusable at all ({retry_exc}).",
                            "error"), flush=True)
                return None
            result["thinking_unsupported"] = True
            return result
        except NoOutputStall as exc:
            print(paint(f"[{args.label}] {model} stopped producing thinking or answer content "
                        f"({exc}).", "warning"), flush=True)
            return None
        except ModelMissing as exc:
            print(paint(f"[{args.label}] {model} is not installed on this runner ({exc}); "
                        f"it has to be pulled before it can be used.", "error"), flush=True)
            return None
        except ModelUnusable as exc:
            print(paint(f"[{args.label}] {model} cannot run here ({exc}).", "error"),
                  flush=True)
            return None

    try:
        result = attempt(request)
        switched = False
        if result is None and args.fallback_model and args.fallback_model != model:
            # Only hand over to a model that is actually on disk. A run whose
            # fallback had never been pulled used to switch to it anyway, take a 404
            # and lose the call entirely - the world plan died that way and the run
            # shipped a procedural world instead of the AI's.
            available = installed_models(args.url)
            if available and args.fallback_model not in available:
                print(paint(f"[{args.label}] {args.fallback_model} is NOT installed "
                            f"(Ollama has: {', '.join(sorted(available)) or 'nothing'}), so "
                            f"there is nothing to hand over to. Trying {model} once more.",
                            "warning"), flush=True)
                print("::warning title=Fallback model missing::"
                      f"{args.fallback_model} was never pulled, so this call could not "
                      f"hand over. Pull it (ollama pull {args.fallback_model}).", flush=True)
            else:
                if not available:
                    print(paint(f"[{args.label}] could not ask Ollama which models it has; "
                                f"trying the fallback anyway.", "warning"), flush=True)
                print(paint(f"[{args.label}] switching to the known-good fallback model "
                            f"{args.fallback_model} so the run continues.", "warning"), flush=True)
                fallback = {**request, "model": args.fallback_model,
                            "think": bool(args.fallback_thinking)}
                result = attempt(fallback, f" (fallback {args.fallback_model})")
                if result is not None:
                    result["fallback_model"] = args.fallback_model
                    switched = True
                    # Sticky hand-over. Every later call in the run names the run's
                    # primary model, so without this the next step would reload the
                    # slow model (minutes), find it slow again, and reload the
                    # fallback: a reload before every single step.
                    stick_to_fallback(args.fallback_model, args.label,
                                      args.output.parent / ".ai_model")
                else:
                    print(paint(f"[{args.label}] the fallback {args.fallback_model} could not "
                                f"answer either; trying {model} once more with the same "
                                f"no-output stall watchdog.", "warning"), flush=True)
        if result is None and not switched:
            # Retry the primary once, but keep the same no-thinking/no-answer stall
            # window. No model is interrupted merely because its measured speed is low.
            print(paint(f"[{args.label}] asking {model} once more; only a full "
                        f"no-thinking/no-answer stall will trigger another hand-off.",
                        "warning"), flush=True)
            result = attempt(request)
        if result is None:
            append_activity({"type": "model_error", "stage": "ollama",
                             "tag": f"[{args.label} AI]", "label": args.label,
                             "provider": "ollama", "model": model,
                             "status": "failed",
                             "reason": "selected and configured fallback models produced no answer"},
                            path=Path("dist/ai_activity.jsonl"), emit=False)
            raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(paint(f"[{args.label}] streaming request failed: {type(exc).__name__}.",
                    "error"), file=sys.stderr, flush=True)
        append_activity({"type": "model_error", "stage": "ollama",
                         "tag": f"[{args.label} AI]", "label": args.label,
                         "provider": "ollama", "model": model,
                         "status": "failed", "reason": f"network failure ({type(exc).__name__})"},
                        path=Path("dist/ai_activity.jsonl"), emit=False)
        raise SystemExit(1) from exc
    if not result["response"].strip():
        print(paint(f"[{args.label}] the model returned an empty answer.", "error"),
              file=sys.stderr, flush=True)
        append_activity({"type": "model_error", "stage": "ollama",
                         "tag": f"[{args.label} AI]", "label": args.label,
                         "provider": "ollama", "model": model,
                         "status": "failed", "reason": "empty answer"},
                        path=Path("dist/ai_activity.jsonl"), emit=False)
        raise SystemExit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result["model"] = request.get("model") if "fallback_model" not in result else result["fallback_model"]
    append_activity({
        "type": "model_response", "stage": "ollama",
        "activity_id": result.get("activity_id"), "tag": f"[{args.label} AI]",
        "label": args.label, "provider": "ollama", "model": result.get("model"),
        "status": "complete", "seconds": result.get("elapsed_seconds"),
        "fallback": bool(result.get("fallback_model")),
        "prompt_messages": request.get("messages", []),
        "thinking": result.get("thinking", ""),
        "output": result.get("response", ""),
    }, path=Path("dist/ai_activity.jsonl"), emit=False)
    args.output.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    first_word = result.get("first_char_seconds")
    first_word_text = (f"first word after {first_word:.0f}s" if first_word is not None else "no timing")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(f"- **{args.label}:** {result['eval_count']} tokens in {result['elapsed_seconds']}s "
                      f"({len(result['response']):,} answer chars, {first_word_text})\n")
    # A machine-readable record of every AI call, next to the model residency log.
    # It is published with the still previews, so "how fast did the next step start"
    # can be answered from the run itself instead of guessed at.
    calls_log = args.output.parent / "ai_calls.jsonl"
    with calls_log.open("a", encoding="utf-8") as out:
        out.write(json.dumps({
            "label": args.label,
            "model": result.get("model") or request.get("model"),
            "first_word_seconds": first_word,
            "elapsed_seconds": result["elapsed_seconds"],
            "tokens": result["eval_count"],
            "tokens_per_second": round(result["eval_count"] / result["elapsed_seconds"], 2)
            if result["elapsed_seconds"] else None,
            # A load is only a load when the weights were genuinely not in RAM.
            "loaded_here": (result.get("model_was_resident") is False
                            or (result.get("model_was_resident") is None
                                and (first_word is None or first_word >= 15))),
            "model_was_resident": result.get("model_was_resident"),
            "prompt_tokens": result.get("prompt_eval_count"),
            "prompt_seconds": result.get("prompt_eval_seconds"),
            "fallback": bool(result.get("fallback_model")),
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
