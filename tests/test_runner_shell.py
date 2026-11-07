"""The public shell repository may contain nothing but one workflow file.

Free runners need a public repository; a public repository shows every file in
it. So the code stays private and only the shell workflow goes public, checking
the private repository out into `src/` with a read-only token.

These tests keep that setup honest: the shell must stay generated (never drifted
from the private workflow), it must run every step inside `src/`, and it must not
carry tool paths that only exist in the private checkout.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runner"))

import make_runner_workflow as shell  # noqa: E402

SOURCE = ROOT / ".github" / "workflows" / "main.yml"
SHELL = ROOT / "runner" / "main.yml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(data: dict) -> dict:
    # PyYAML reads a bare `on:` key as the boolean True.
    return data.get("on") or data.get(True) or {}


class GeneratedShellTests(unittest.TestCase):
    def test_the_shell_is_up_to_date(self):
        self.assertEqual(SHELL.read_text(encoding="utf-8"), shell.build(),
                         "run: python3 runner/make_runner_workflow.py")

    def test_it_checks_the_private_repo_out_with_a_secret_token(self):
        job = load(SHELL)["jobs"]["generate_roblox_short"]
        first = job["steps"][0]
        self.assertEqual(first["uses"], "actions/checkout@v4")
        self.assertEqual(first["with"]["repository"], "Nishgamerrz/Ai-rant")
        self.assertEqual(first["with"]["token"], "${{ secrets.SOURCE_TOKEN }}")
        self.assertEqual(first["with"]["path"], "src")

    def test_every_run_step_runs_inside_the_private_checkout(self):
        job = load(SHELL)["jobs"]["generate_roblox_short"]
        self.assertEqual(job["defaults"]["run"]["working-directory"], "src")
        for step in job["steps"]:
            if "run" in step:
                cwd = step.get("working-directory", "src")
                self.assertTrue(cwd == "src" or cwd.startswith("src/"),
                                f"step {step.get('name')!r} would run outside src/ ({cwd})")

    def test_repo_paths_are_prefixed(self):
        job = load(SHELL)["jobs"]["generate_roblox_short"]
        text = SHELL.read_text(encoding="utf-8")
        self.assertIn("cache-dependency-path: src/tools/video_renderer/package-lock.json", text)
        self.assertIn("working-directory: src/tools/video_renderer", text)
        uploads = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertEqual(len(uploads), 2)
        for step in uploads:
            paths = step["with"]["path"]
            entries = paths if isinstance(paths, list) else [paths]
            for entry in entries:
                self.assertTrue(entry.strip().startswith("src/"),
                                f"artifact path {entry!r} is outside the private checkout")

    def test_the_same_inputs_and_steps_survive(self):
        private = load(SOURCE)
        public = load(SHELL)
        self.assertEqual(list(private["jobs"]), list(public["jobs"]))
        wanted = private["jobs"]["generate_roblox_short"]
        got = public["jobs"]["generate_roblox_short"]
        self.assertEqual(wanted["timeout-minutes"], got["timeout-minutes"])
        self.assertEqual(
            list(triggers(private)["workflow_dispatch"]["inputs"]),
            list(triggers(public)["workflow_dispatch"]["inputs"]))
        self.assertEqual(
            [i["default"] for i in triggers(private)["workflow_dispatch"]["inputs"].values()],
            [i["default"] for i in triggers(public)["workflow_dispatch"]["inputs"].values()])
        private_steps = [s.get("name") for s in wanted["steps"]]
        public_steps = [s.get("name") for s in got["steps"]]
        # Only the checkout step differs.
        self.assertEqual(
            [n for n in private_steps if n != "Checkout repository"],
            [n for n in public_steps if n != "Check out the private generator (read-only)"])

    def test_the_shell_carries_no_project_code(self):
        text = SHELL.read_text(encoding="utf-8")
        for leak in ("def main(", "import yaml", "users/normal.obj", "class "):
            self.assertNotIn(leak, text)
        # It is still one workflow file, not a copy of the tree.
        self.assertLess(len(text.splitlines()), 1200)


class RepositoryHygieneTests(unittest.TestCase):
    def test_the_runner_folder_holds_only_the_shell_and_its_docs(self):
        allowed = {"main.yml", "README.md", "make_runner_workflow.py"}
        names = {p.name for p in (ROOT / "runner").iterdir() if p.name != "__pycache__"}
        self.assertEqual(names, allowed)

    def test_forks_and_pull_requests_never_receive_the_source_token(self):
        # The secret is read by a checkout step. Fork PRs never get secrets, but the
        # workflow should also not be triggerable by pull_request at all.
        self.assertEqual(list(triggers(load(SHELL))), ["workflow_dispatch"])


if __name__ == "__main__":
    unittest.main()
