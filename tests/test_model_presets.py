from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from model_presets import (  # noqa: E402
    DEFAULT_MODEL,
    MODEL_MAP,
    MODEL_PRESETS,
    normalize_model_quality,
    resolve_model,
    selection_fields,
)


EXPECTED = {
    "fast": ("Fast", "qwen3:4b", "qwen3-4b-v1", 8, 3600),
    "medium": ("Medium", "qwen3:8b", "qwen3-8b-v1", 8, 3600),
    "hard": ("Hard", "qwen3:8b", "qwen3-8b-v3", 8, 5400),
    "smart_11b": ("Smart 11B", "qwen3:14b", "qwen3-14b-v1", 20, 9000),
    "animation_best": ("Animation", "deepseek-r1:8b", "deepseek-r1-8b-v1", 14, 7200),
}


class ModelPresetManifestTests(unittest.TestCase):
    def test_every_advertised_preset_resolves_to_its_exact_model_and_run_metadata(self):
        self.assertEqual(list(MODEL_PRESETS), list(EXPECTED))
        for quality, (label, model, cache, minimum_gib, timeout_seconds) in EXPECTED.items():
            with self.subTest(quality=quality):
                preset = MODEL_PRESETS[quality]
                self.assertEqual(preset["label"], label)
                self.assertEqual(preset["model"], model)
                self.assertEqual(preset["cache_version"], cache)
                self.assertEqual(preset["minimum_gib"], minimum_gib)
                self.assertEqual(preset["timeout_seconds"], timeout_seconds)
                self.assertEqual(MODEL_MAP[quality], model)
                self.assertEqual(normalize_model_quality(f" {quality.upper()} "), quality)
                self.assertEqual(resolve_model(quality), model)
                self.assertEqual(selection_fields(quality)["selected_model"], model)

        self.assertEqual(MODEL_MAP["fast"], "qwen3:4b")
        self.assertEqual(MODEL_MAP["medium"], "qwen3:8b")
        self.assertEqual(MODEL_MAP["hard"], "qwen3:8b")
        self.assertEqual(DEFAULT_MODEL, "qwen3:8b")

    def test_action_resolver_writes_one_consistent_selection_record(self):
        helper = ROOT / "tools/model_presets.py"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            selection = Path(directory) / "dist" / "model_selection.json"
            result = subprocess.run(
                [sys.executable, str(helper), "fast", "--github-output", str(output),
                 "--json-output", str(selection)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Model preset Fast (fast) resolves to Ollama model qwen3:4b", result.stdout)
            self.assertIn("quality=fast", output.read_text(encoding="utf-8"))
            self.assertIn("selected_model=qwen3:4b", output.read_text(encoding="utf-8"))
            self.assertEqual(
                json.loads(selection.read_text(encoding="utf-8")),
                {
                    "quality": "fast",
                    "label": "Fast",
                    "selected_model": "qwen3:4b",
                    "cache_version": "qwen3-4b-v1",
                    "minimum_gib": 8,
                    "timeout_seconds": 3600,
                },
            )

    def test_unknown_presets_fail_instead_of_silently_resolving_to_medium_or_hard(self):
        with self.assertRaisesRegex(ValueError, "Unknown model quality"):
            normalize_model_quality("turbo")
        with self.assertRaisesRegex(ValueError, "Unknown model quality or Ollama model"):
            resolve_model("turbo")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/model_presets.py"), "turbo",
                 "--github-output", str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("fast, medium, hard, smart_11b, animation_best", result.stderr)
            self.assertFalse(output.exists())

    def test_explicit_ollama_tag_is_preserved_and_never_replaced(self):
        self.assertEqual(resolve_model("qwen3:4b"), "qwen3:4b")
        with self.assertRaisesRegex(ValueError, "Unknown model quality"):
            resolve_model("not-a-preset")
        agent = (ROOT / "tools/nish_agent.py").read_text(encoding="utf-8")
        self.assertIn("from model_presets import DEFAULT_MODEL, MODEL_MAP, resolve_model", agent)
        self.assertIn("model = resolve_model(preset)", agent)
        self.assertNotIn("preset if \":\" in preset else DEFAULT_MODEL", agent)


class ModelPresetPropagationTests(unittest.TestCase):
    def test_frontend_and_dispatch_share_the_preset_manifest(self):
        selector = (ROOT / "web/components/ModelSelector.tsx").read_text(encoding="utf-8")
        route = (ROOT / "web/app/api/github/dispatch/route.ts").read_text(encoding="utf-8")
        short_page = (ROOT / "web/app/rbxshort/page.tsx").read_text(encoding="utf-8")
        modal = (ROOT / "web/components/NewChatModal.tsx").read_text(encoding="utf-8")

        self.assertIn("MODEL_IDS, MODEL_PRESETS", selector)
        self.assertIn("desc: `${preset.model} · ${preset.summary}`", selector)
        self.assertIn("normalizeModelId(body.model_quality || body.model || \"hard\")", route)
        self.assertIn("model_quality: modelQuality", route)
        self.assertIn("model_label: preset.label", route)
        self.assertIn("selected_model: preset.model", route)
        self.assertIn("model_quality: model", short_page)
        self.assertIn("model_quality: model", modal)
        self.assertIn("Dispatch resolved", modal)

    def test_both_workflows_consume_the_resolved_outputs_not_handwritten_model_maps(self):
        main = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        agent_workflow = (ROOT / ".github/workflows/agent.yml").read_text(encoding="utf-8")

        self.assertIn("id: model-preset", main)
        self.assertIn('python tools/model_presets.py "$MODEL_QUALITY"', main)
        self.assertIn("MODEL_QUALITY: ${{ steps.model-preset.outputs.quality }}", main)
        self.assertIn("SELECTED_MODEL: ${{ steps.model-preset.outputs.selected_model }}", main)
        self.assertIn("MODEL_TIMEOUT_SECONDS: ${{ steps.model-preset.outputs.timeout_seconds }}", main)
        self.assertIn("MODEL_REQUIRED_GIB: ${{ steps.model-preset.outputs.minimum_gib }}", main)
        self.assertIn("steps.model-preset.outputs.cache_version", main)
        self.assertIn("dist/model_selection.json", main)
        self.assertIn("Selected local model:", main)
        self.assertIn("Selected preset $MODEL_PRESET_LABEL ($MODEL_QUALITY) -> Ollama model $SELECTED_MODEL", main)

        self.assertIn("id: model-preset", agent_workflow)
        self.assertIn('python3 tools/model_presets.py "$MODEL_QUALITY"', agent_workflow)
        self.assertIn("MODEL_QUALITY: ${{ steps.model-preset.outputs.quality }}", agent_workflow)
        self.assertIn("SELECTED_MODEL: ${{ steps.model-preset.outputs.selected_model }}", agent_workflow)
        self.assertIn("dist/model_selection.json", agent_workflow)
        self.assertNotIn("fast) SELECTED_MODEL=qwen3:4b", main + agent_workflow)
        self.assertNotIn("medium) SELECTED_MODEL=qwen3:8b", main + agent_workflow)
        self.assertNotIn("hard) SELECTED_MODEL=qwen3:8b", main + agent_workflow)


if __name__ == "__main__":
    unittest.main()
