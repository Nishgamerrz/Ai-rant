"""Nothing half-merged may reach a workflow.

A merge conflict was once resolved by hand in a hurry and the markers in
`.github/workflows/studio-experience-tests.yml` were committed. GitHub then
cannot parse the file at all: the whole validation workflow silently stops
running, and every push looks green because there is no workflow left to fail.
That is worse than a normal breakage, so it is checked directly.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


def watched_files():
    patterns = [".github/workflows/*.yml", ".github/workflows/*.yaml", "tools/**/*.py",
                "tools/**/*.mjs", "tests/*.py", "*.md", "*.toml", "*.json"]
    seen = set()
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if "node_modules" in path.parts or path in seen or not path.is_file():
                continue
            seen.add(path)
            yield path


class NoConflictMarkersTests(unittest.TestCase):
    def test_no_tracked_source_file_contains_a_conflict_marker(self):
        broken = []
        for path in watched_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                if line.startswith(MARKERS):
                    broken.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(broken, [], "conflict markers would break these files: " + ", ".join(broken[:5]))

    def test_every_workflow_file_parses(self):
        for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
            with self.subTest(path=path.name):
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict, f"{path.name} did not parse as a workflow")

    def test_the_validation_workflow_smokes_every_renderer_test(self):
        """Every test:* script in the renderer must actually run in CI."""
        import json
        scripts = json.loads((ROOT / "tools/video_renderer/package.json").read_text(encoding="utf-8"))["scripts"]
        # Some run in the validation workflow, some in the generator's own
        # preflight step; either is fine, running nowhere is not.
        ran = "\n".join(path.read_text(encoding="utf-8")
                        for path in (ROOT / ".github/workflows").glob("*.yml"))
        missing = [name for name in scripts if name.startswith("test:") and f"npm run {name}" not in ran]
        self.assertEqual(missing, [], f"these renderer tests never run in CI: {missing}")


if __name__ == "__main__":
    unittest.main()
