"""On-screen story captions and the short-form narrator voice.

Two changes asked for together:

* the spoken line is drawn on the video itself - centred, a little above the
  middle of the vertical frame, in bold outlined story-short style - instead of
  living only in the SRT file;
* the male narrator sounds like a Roblox YouTube short: young, bright and quick,
  not the slow audiobook read the old -8% rate produced.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools" / "video_renderer"
RENDER_SHORT = (RENDERER / "render_short.mjs").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")


class CaptionOverlayTests(unittest.TestCase):
    def test_the_caption_lives_in_the_page_so_it_is_captured(self):
        # Frames are screenshots of #frame, so an ffmpeg drawtext filter would not
        # survive the -vf scale chain; the caption must be inside the page.
        self.assertIn('<div id="caption"></div>', RENDER_SHORT)
        self.assertIn("position:absolute", RENDER_SHORT)
        self.assertIn("#caption.on{opacity:1}", RENDER_SHORT)

    def test_it_sits_a_little_above_the_middle_not_at_the_top(self):
        import re

        style = RENDER_SHORT[RENDER_SHORT.index("#caption{"):RENDER_SHORT.index("#caption.on")]
        top = float(re.search(r"top:([\d.]+)%", style).group(1))
        # "like the middle but a little up": near the centre, above it.
        self.assertGreaterEqual(top, 30.0)
        self.assertLessEqual(top, 45.0)

    def test_it_is_centred_and_readable_like_story_shorts(self):
        self.assertIn("left:50%", RENDER_SHORT)
        self.assertIn("translate(-50%,-50%)", RENDER_SHORT)
        self.assertIn("text-transform:uppercase", RENDER_SHORT)
        self.assertIn("-webkit-text-stroke", RENDER_SHORT)
        self.assertIn("font-weight:900", RENDER_SHORT)
        self.assertIn("text-align:center", RENDER_SHORT)

    def test_every_rendered_frame_updates_it(self):
        render_at = RENDER_SHORT[RENDER_SHORT.index("window.renderAt=async(t)=>{"):]
        self.assertIn("captionAt(t)", render_at[:400])

    def test_it_follows_the_narration_and_hides_between_lines(self):
        self.assertIn("for(const cue of captions)", RENDER_SHORT)
        self.assertIn("captionEl.classList.toggle('on',Boolean(text))", RENDER_SHORT)

    def test_the_srt_is_still_the_source_of_the_text(self):
        self.assertIn("captions:captionCues", RENDER_SHORT)
        self.assertIn("args.captions", RENDER_SHORT)


class NarratorVoiceTests(unittest.TestCase):
    def test_the_male_voice_is_a_bright_short_form_read(self):
        block = WORKFLOW[WORKFLOW.index("case \"$VOICE_STYLE\" in\n            male)"):
                         WORKFLOW.index("NARRATOR_VOICE=$VOICE")]
        self.assertIn('male) VOICE_CANDIDATES="en-US-BrianNeural en-US-GuyNeural"', block)
        self.assertIn("RATE=+4%", block)
        self.assertIn("PITCH=+4Hz", block)
        # The old slow audiobook read is gone.
        self.assertNotIn("RATE=-8%", block)

    def test_a_missing_voice_falls_back_instead_of_failing_the_run(self):
        self.assertIn("for CANDIDATE in $VOICE_CANDIDATES; do", WORKFLOW)
        self.assertIn("was unavailable; trying the next one", WORKFLOW)
        self.assertIn('test -n "$VOICE"', WORKFLOW)

    def test_a_short_read_is_filled_before_it_is_reported(self):
        # Run #82: 262 words became 106 s of a 164 s video, so 58 seconds of the
        # finished short were silent. The script is now sized at the measured
        # 2.45 words per second, the voice is retried at a slower rate when it
        # still runs short, and only then is anything reported.
        self.assertIn("DURATION_SECONDS * 245 / 100", WORKFLOW)
        self.assertIn("FILL_RATE", WORKFLOW)
        self.assertIn("Filled the length", WORKFLOW)
        self.assertIn("seconds < target * 0.9", WORKFLOW)
        self.assertIn("the narration ends", WORKFLOW)

    def test_the_warning_names_the_rate_it_actually_used(self):
        # The old message printed an empty "()" because GITHUB_ENV set in the same
        # step is not visible to that step's environment.
        self.assertIn('os.environ.get("NARRATOR_RATE") or os.environ.get("RATE")', WORKFLOW)
        self.assertNotIn('os.environ.get("NARRATOR_RATE", "")', WORKFLOW)

    def test_every_voice_choice_still_exists(self):
        for style in ("male)", "female)", "thin_male)"):
            self.assertIn(style, WORKFLOW)


@unittest.skipUnless(shutil.which("node"), "node is not available here")
class CaptionSmokeTest(unittest.TestCase):
    def test_the_browser_free_caption_check_passes(self):
        result = subprocess.run(["node", "caption_smoke_test.mjs"], cwd=RENDERER,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
        self.assertIn("On-screen caption check passed", result.stdout)

    def test_it_runs_in_the_validate_workflow(self):
        data = json.loads((RENDERER / "package.json").read_text())
        self.assertEqual(data["scripts"]["test:caption-overlay"], "node caption_smoke_test.mjs")
        ci = (ROOT / ".github" / "workflows" / "studio-experience-tests.yml").read_text()
        self.assertIn("npm run test:caption-overlay", ci)


if __name__ == "__main__":
    unittest.main()
