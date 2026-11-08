"""The world must not render black, and a run must prove it before shipping.

Every finished MP4 the owner opened looked wrong in the same two ways: parts of
the world came out as solid black slabs, and mismatched geometry read as
stretched. The black slabs had a precise cause: the instanced map material asked
for vertex colours while the geometry had no colour attribute, so three's
`vColor *= color` multiplied every Part by an unbound attribute - zero - and the
whole world was drawn black.

These tests pin the cause down, and pin the safety net that now measures real
frames while the video is rendered instead of leaving it to the viewer.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
START = (ROOT / ".github/workflows/start.yml").read_text(encoding="utf-8")
THREE = ROOT / "tools/video_renderer/node_modules/three"


class BlackWorldTests(unittest.TestCase):
    def test_the_instanced_material_does_not_ask_for_vertex_colours(self):
        # The exact line that made every Part black.
        material = re.search(r"new THREE\.MeshStandardMaterial\(\{color:0xffffff[^\n]*", RENDERER)
        self.assertIsNotNone(material, "the instanced map material moved; update this test")
        line = material.group(0)
        self.assertNotIn("vertexColors:true", line.replace(" ", ""))

    def test_per_part_colour_still_comes_from_set_color_at(self):
        # instanceColor is what carries a Part's own colour once vertex colours
        # are gone, so the two must always be changed together.
        self.assertIn("setColorAt", RENDERER)
        self.assertNotIn("vertexColors:true", RENDERER.replace(" ", ""))

    def test_a_vertex_colour_material_without_colours_is_refused(self):
        self.assertIn("asks for vertex colours the geometry does not have", RENDERER)

    def test_three_really_multiplies_by_the_unbound_attribute(self):
        # Explains the bug, and fails loudly if three ever changes the rule.
        chunk = THREE / "src/renderers/shaders/ShaderChunk/color_vertex.glsl.js"
        if not chunk.exists():
            self.skipTest("three sources are not installed")
        text = chunk.read_text(encoding="utf-8")
        self.assertIn("vColor *= color;", text)
        programs = (THREE / "src/renderers/webgl/WebGLPrograms.js").read_text(encoding="utf-8")
        self.assertIn("vertexColors: material.vertexColors", programs)


class NoStretchTests(unittest.TestCase):
    """Correct dimensions are not proof of an undistorted picture."""

    def test_the_page_measures_square_pixels_against_the_real_canvas(self):
        self.assertIn("window.probeProjection", RENDERER)
        self.assertIn("pixelsPerUnitX", RENDERER)
        self.assertIn("stretch:", RENDERER)
        # The camera aspect is taken from the drawing buffer, not from a constant
        # that could drift away from what the browser actually rasterises.
        self.assertIn("camera.aspect=size.x/size.y", RENDERER)

    def test_an_off_ratio_canvas_or_projection_stops_the_render(self):
        self.assertIn("the MP4 would be scaled off-ratio and look stretched", RENDERER)
        self.assertIn("The picture is stretched", RENDERER)
        self.assertIn("is stretched:", RENDERER)

    def test_the_video_declares_square_pixels(self):
        self.assertIn("scale=1440:2560:flags=lanczos,setsar=1", RENDERER)
        self.assertIn("-aspect 9:16", WORKFLOW)

    def test_the_shipped_mp4_is_probed_for_stretch_flags(self):
        validator = (ROOT / "tools/validate_short.py").read_text(encoding="utf-8")
        self.assertIn("sample_aspect_ratio", validator)
        self.assertIn("players will stretch this 9:16 short", validator)
        self.assertIn("rotation flag", validator)

    def test_the_start_of_run_preflight_also_refuses_a_stretched_picture(self):
        preflight = RENDERER.split("async function preflight(")[1]
        self.assertIn("window.probeProjection()", preflight)
        self.assertIn("would be rescaled and stretched", preflight)
        self.assertIn("the picture is stretched", preflight)

    def test_the_start_of_run_preflight_also_refuses_a_black_or_grey_picture(self):
        preflight = RENDERER.split("async function preflight(")[1]
        self.assertIn("await measureJpeg(shot)", preflight)
        # The same thresholds as the sampled audit, so the two cannot disagree.
        self.assertIn("health.blackFraction > 0.55", preflight)
        self.assertIn("health.colourFraction < 0.05", preflight)

    def test_the_projection_maths_is_proved_without_a_gpu(self):
        test = (ROOT / "tools/video_renderer/projection_smoke_test.mjs").read_text(encoding="utf-8")
        self.assertIn("ratio 1.000", test)
        self.assertIn("2% gate", test)
        self.assertIn('"test:projection"', (ROOT / "tools/video_renderer/package.json").read_text(encoding="utf-8"))

    def test_the_projection_probe_runs_before_the_first_encoded_frame(self):
        probe = RENDERER.index("Projection probe:")
        first_frame = RENDERER.index("for(let frame=0;frame<totalFrames;frame++)")
        self.assertLess(probe, first_frame)


class FrameAuditTests(unittest.TestCase):
    def test_the_audit_measures_the_pixels_that_are_encoded(self):
        for key in ("meanLuminance", "blackFraction", "colourFraction", "centreBlackFraction"):
            self.assertIn(key, RENDERER)
        # Reading a WebGL canvas back from a separate task returns an empty
        # buffer, which reported a bright frame as 100% black. The audit decodes
        # the exact JPEG that is piped into ffmpeg instead.
        self.assertIn("async function measureJpeg(jpeg)", RENDERER)
        self.assertNotIn("window.measureFrame", RENDERER)
        self.assertIn("const stats=await measureJpeg(jpeg)", RENDERER)
        self.assertIn("...await measureJpeg(shot)", RENDERER)

    def test_the_renderer_reports_the_audit(self):
        self.assertIn("Frame audit over", RENDERER)

    def test_a_black_world_stops_the_render(self):
        self.assertIn("The world renders black", RENDERER)
        self.assertIn("The world renders colourless", RENDERER)

    def test_still_previews_are_written(self):
        self.assertIn("args.preview", RENDERER)
        self.assertIn("args.preview", RENDERER)
        self.assertIn("frame_${previewFrame.get(frame)}", RENDERER)

    def test_a_rejected_preflight_frame_is_kept_for_inspection(self):
        preflight = RENDERER.split("async function preflight(")[1]
        # Saved before the checks run, so a rejected frame still reaches the run's
        # artifacts and the preview branch: looking at the picture is how you fix it.
        self.assertIn("preflight-frame.jpg", preflight)
        save = preflight.index("preflight-frame.jpg")
        self.assertLess(save, preflight.index("the frame is blown out"))
        self.assertIn("preflight-frame.jpg", WORKFLOW)

    def test_over_exposure_is_named_as_such(self):
        self.assertIn("the frame is blown out", RENDERER)
        self.assertIn("the lighting is over-exposed", RENDERER)

    def test_the_renderer_uses_a_film_curve_instead_of_clipping(self):
        # NoToneMapping clipped every lit surface to white and destroyed the
        # colour, which measured as 251/255 luminance with 0.2% colour.
        self.assertIn("THREE.ACESFilmicToneMapping", RENDERER)
        self.assertNotIn("THREE.NoToneMapping", RENDERER)
        self.assertIn("toneMappingExposure", RENDERER)

    def test_the_workflow_asks_for_previews_and_uploads_them(self):
        self.assertIn("--preview dist/preview", WORKFLOW)
        self.assertIn("short-preview-stills", WORKFLOW)

    def test_previews_are_published_beside_the_repo_for_quick_looking(self):
        self.assertIn("publish_preview", WORKFLOW)
        self.assertIn("media-preview", WORKFLOW)
        self.assertIn("permissions:\n      contents: write", WORKFLOW)
        # A called workflow cannot exceed its caller, so the backup button needs it too.
        self.assertIn("contents: write", START)

    def test_two_comparison_runs_do_not_overwrite_each_others_stills(self):
        # A hard run and a smart_11b run dispatched from the same workflow used to
        # share one artifact name and one branch, so the second silently replaced
        # the first. Both are namespaced by the model preset now.
        self.assertIn("name: short-preview-stills-${{ inputs.model_quality || 'default' }}", WORKFLOW)
        self.assertIn('BRANCH="media-preview-${{ inputs.model_quality || \'default\' }}"', WORKFLOW)
        self.assertNotIn('name: short-preview-stills\n', WORKFLOW)
        self.assertIn('git push -q --force "https://x-access-token:${{ github.token }}@github.com/${{ github.repository }}.git" "$BRANCH"', WORKFLOW)

    def test_publishing_can_never_fail_the_run(self):
        block = WORKFLOW.split("publish_preview:")[1]
        self.assertIn("continue-on-error: true", block)


if __name__ == "__main__":
    unittest.main()


class EncodedFrameMeasurementTests(unittest.TestCase):
    """The audit must read the shipped pixels, and must not invent a black world.

    A WebGL canvas read back from a different task is empty once the compositor
    has cleared it. That is what reported a bright preflight frame as "100% pure
    black" and stopped two real runs, so the reader itself is checked here.
    """

    def test_the_measurer_decodes_raw_pixels_through_ffmpeg(self):
        body = RENDERER.split("async function measureJpeg(jpeg)", 1)[1].split("async function preflight(", 1)[0]
        self.assertIn("'-f', 'image2pipe'", body)
        self.assertIn("'-pix_fmt', 'rgb24'", body)
        self.assertIn("'-f', 'rawvideo'", body)
        self.assertIn("PROBE_WIDTH * PROBE_HEIGHT * 3", body)

    def test_a_failed_decode_is_an_error_not_a_black_frame(self):
        body = RENDERER.split("async function measureJpeg(jpeg)", 1)[1].split("const BASE_ARGS", 1)[0]
        self.assertIn("could not measure a rendered frame", body)
        self.assertIn("raw.length}/${expected} bytes", body)
        # Silence would turn a broken probe into a mysterious "the world is black".
        self.assertNotIn("catch", body)
