#!/usr/bin/env python3
"""Print one line of workflow narration in the same palette as the AI log.

The pipeline's own status lines used to be plain ``echo`` calls, so the console
was a grey wall with a few coloured AI lines in it: you could not tell a section
heading from a warning at a glance. This helper gives every line a colour, using
exactly the same codes as the model output, so the whole run reads as one thing.

Usage:
    python tools/say.py plan "Token budget for this 165s story: 2520"
    python tools/say.py success "World blueprint accepted."
    python tools/say.py warning "Blueprint rejected; correcting and retrying."

Colour follows ``AI_COLOR`` exactly like the rest of the console: on in Actions,
off when the output is piped into a file or a test.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import paint  # noqa: E402

# Every kind in console_style.CODES is accepted; the short list here is only the
# default when a caller passes something a shell typo produced.
KINDS = ("thinking", "answer", "label", "notice", "success", "warning", "error",
         "tool", "plan", "thought", "frame")
DEFAULT_KIND = "plan"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: say.py <kind> <text...>", file=sys.stderr)
        return 2
    kind = argv[0] if argv[0] in KINDS else DEFAULT_KIND
    # The first argument always occupies the kind slot; an unrecognised kind is
    # treated as the default rather than being dumped into the message.
    text = " ".join(argv[1:])
    print(paint(text, kind), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
