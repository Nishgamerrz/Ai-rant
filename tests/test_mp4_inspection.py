"""The shipped MP4 must be inspected, not assumed.

Everything checked before this measured the renderer. These tests cover the part
that measures the file that actually ships: the container properties a player
uses to decide how to stretch the picture, and the decoded pixels a viewer sees.

The frame analysis is pure Python over an rgb24 buffer, so it can be proved here
without ffmpeg or a GPU: a colourful world passes, and black frames, blown-out
frames, flat frames and black slabs are all named.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import inspect_short as short  # noqa: E402

WORKFLOW = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")


def buffer(painter) -> bytes:
    """Build a 180x320 rgb24 buffer from a per-pixel function."""
    out = bytearray()
    for y in range(short.PROBE_HEIGHT):
        for x in range(short.PROBE_WIDTH):
            out.extend(painter(x, y))
    return bytes(out)


def colourful_world(x, y):
    """A lit ground with sky above and a red roof: the shape of a real frame."""
    if y < 90:
        return (150, 200, 240)                       # sky
    if y < 150:
        return (196, 104, 74) if x % 40 < 30 else (150, 160, 175)   # roof / wall
    return (126, 182, 120) if (x + y) % 7 else (110, 160, 108)      # grass with texture


def black_slab_world(x, y):
    """A normal world with one Part that never got its colour."""
    if 60 <= x < 130 and 180 <= y < 300:
        return (4, 4, 4)
    return colourful_world(x, y)


class ContainerTests(unittest.TestCase):
    def probe(self, **overrides):
        video = {
            "codec_type": "video", "codec_name": "h264", "width": 1440, "height": 2560,
            "sample_aspect_ratio": "1:1", "display_aspect_ratio": "9:16",
            "avg_frame_rate": "30/1", "duration": "120.0", "pix_fmt": "yuv420p",
            "side_data_list": [{"rotation": 0}],
        }
        video.update(overrides)
        return {
            "streams": [video, {"codec_type": "audio", "codec_name": "aac", "duration": "120.0"}],
            "format": {"size": str(150 * 1024 * 1024), "duration": "120.0"},
        }

    def test_a_correct_short_has_no_problems(self):
        problems, facts = short.container_problems(self.probe())
        self.assertEqual(problems, [])
        self.assertEqual((facts["width"], facts["height"]), (1440, 2560))
        self.assertAlmostEqual(facts["sample_aspect"], 1.0)
        self.assertAlmostEqual(facts["display_aspect"], 0.5625)

    def test_a_non_square_sample_aspect_ratio_is_a_stretch(self):
        problems, _ = short.container_problems(self.probe(sample_aspect_ratio="4:3"))
        self.assertTrue(any("stretch" in problem for problem in problems), problems)

    def test_a_rotation_flag_is_a_stretch(self):
        problems, _ = short.container_problems(self.probe(side_data_list=[{"rotation": -90}]))
        self.assertTrue(any("rotation" in problem for problem in problems), problems)

    def test_a_rescaled_frame_is_refused(self):
        problems, _ = short.container_problems(self.probe(width=1920, height=1080,
                                                          display_aspect_ratio="16:9"))
        self.assertTrue(any("1440x2560" in problem for problem in problems), problems)

    def test_missing_narration_is_refused(self):
        info = self.probe()
        info["streams"] = [info["streams"][0]]
        with self.assertRaises(short.InspectionError):
            short.container_problems(info)

    def test_a_zero_sample_aspect_ratio_is_read_as_square(self):
        # ffprobe writes "0:1" when it does not know, which is not a stretch.
        self.assertEqual(short.ratio("0:1"), 1.0)
        self.assertEqual(short.ratio(None), 1.0)
        self.assertAlmostEqual(short.ratio("4:3"), 4 / 3)


class FrameMeasurementTests(unittest.TestCase):
    def test_a_real_world_passes(self):
        stats = short.measure_frame(buffer(colourful_world))
        self.assertEqual(short.frame_problems("frame", stats, short.find_black_slabs(buffer(colourful_world))), [])
        self.assertGreater(stats["colour_fraction"], 0.5)
        self.assertGreater(stats["contrast"], 20)

    def test_a_black_world_is_named(self):
        stats = short.measure_frame(buffer(lambda x, y: (2, 2, 2)))
        problems = short.frame_problems("frame", stats, short.find_black_slabs(buffer(lambda x, y: (2, 2, 2))))
        self.assertTrue(any("pure black" in problem for problem in problems), problems)

    def test_a_blown_out_world_is_named(self):
        stats = short.measure_frame(buffer(lambda x, y: (255, 255, 255)))
        problems = short.frame_problems("frame", stats, [])
        self.assertTrue(any("blown-out" in problem for problem in problems), problems)

    def test_a_flat_frame_is_named(self):
        stats = short.measure_frame(buffer(lambda x, y: (140, 150, 160)))
        problems = short.frame_problems("frame", stats, [])
        self.assertTrue(any("flat" in problem for problem in problems), problems)

    def test_a_colourless_frame_is_named(self):
        stats = short.measure_frame(buffer(lambda x, y: (128, 128, 128) if (x + y) % 5 else (150, 150, 150)))
        problems = short.frame_problems("frame", stats, [])
        self.assertTrue(any("colourless" in problem for problem in problems), problems)


class BlackBlockTests(unittest.TestCase):
    def test_a_black_part_is_found_as_a_rectangular_slab(self):
        slabs = short.find_black_slabs(buffer(black_slab_world))
        self.assertTrue(slabs, "the black Part was not detected")
        biggest = slabs[0]
        self.assertGreater(biggest["fill"], 0.05)
        self.assertGreater(biggest["squareness"], 0.9)
        # Its position is reported so the frame can be looked at.
        self.assertGreater(biggest["x"], 0.2)
        self.assertLess(biggest["x"], 0.6)

    def test_the_black_part_fails_the_frame(self):
        raw = buffer(black_slab_world)
        stats = short.measure_frame(raw)
        problems = short.frame_problems("frame", stats, short.find_black_slabs(raw))
        self.assertTrue(any("black block" in problem for problem in problems), problems)

    def test_a_clean_world_has_no_slabs(self):
        self.assertEqual(short.find_black_slabs(buffer(colourful_world)), [])

    def test_shadows_are_not_reported_as_blocks(self):
        # A soft dark band along the bottom is shading, not a Part with no colour.
        def shaded(x, y):
            red, green, blue = colourful_world(x, y)
            factor = 0.55 if y > 250 else 1.0
            return (int(red * factor), int(green * factor), int(blue * factor))
        slabs = [slab for slab in short.find_black_slabs(buffer(shaded))
                 if slab["fill"] >= 0.05 and slab["squareness"] >= 0.8]
        self.assertEqual(slabs, [])


class WorkflowWiringTests(unittest.TestCase):
    def test_the_workflow_inspects_the_shipped_mp4(self):
        self.assertIn("tools/inspect_short.py", WORKFLOW)
        self.assertIn("--video dist/Roblox_2K_YouTube_Short.mp4", WORKFLOW)
        self.assertIn("--frames-dir dist/preview", WORKFLOW)
        self.assertIn("--report dist/mp4_inspection.md", WORKFLOW)

    def test_the_inspection_runs_after_the_mp4_is_validated(self):
        self.assertLess(WORKFLOW.index("tools/validate_short.py"),
                        WORKFLOW.index("tools/inspect_short.py"))

    def test_a_broken_mp4_still_uploads_but_still_fails_the_run(self):
        # continue-on-error keeps the artifact for inspection; a later gate makes
        # the run red, so a bad picture is never reported as a good run.
        step = WORKFLOW.split("- name: Inspect the finished MP4 and its own frames")[1]
        step = step.split("- name:", 1)[0]
        self.assertIn("continue-on-error: true", step)
        self.assertIn("id: mp4-inspection", step)
        self.assertIn("steps.mp4-inspection.outcome == 'failure'", WORKFLOW)

    def test_the_report_and_frames_are_published(self):
        publish = WORKFLOW.split("publish_preview:")[1]
        self.assertIn("mp4_inspection.md", publish)
        self.assertIn("mp4_", publish)


if __name__ == "__main__":
    unittest.main()
