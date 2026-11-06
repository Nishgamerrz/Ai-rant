import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENTENCE = "Maya walked home slowly and thought about the wallet she had found earlier today."


def write_response(directory: Path, words: int) -> Path:
    body = " ".join([SENTENCE] * max(1, words // 13 + 1)).split()
    path = directory / "narration_response.json"
    path.write_text(json.dumps({"message": {"content": json.dumps({"narration": " ".join(body[:words])})}}),
                    encoding="utf-8")
    return path


class LongFormNarrationTests(unittest.TestCase):
    def run_prepare(self, words: int, duration: int):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            response = write_response(work, words)
            output = work / "narration.txt"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/prepare_narration.py"), str(response), str(output),
                 str(duration)],
                capture_output=True, text=True, check=False)
            text = output.read_text(encoding="utf-8") if output.exists() else ""
        return result, text

    def test_three_minute_short_accepts_a_full_length_story(self):
        result, text = self.run_prepare(290, 180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreaterEqual(len(text.split()), 270)

    def test_old_hundred_word_cap_is_gone(self):
        # 120 words used to trip the hard cap; for a 180s short it is too short.
        result, _ = self.run_prepare(120, 180)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target", (result.stdout + result.stderr).lower())
        # ...and 120 words is still perfectly valid for a 60 second short.
        result_short, _ = self.run_prepare(100, 60)
        self.assertEqual(result_short.returncode, 0, result_short.stdout + result_short.stderr)


if __name__ == "__main__":
    unittest.main()
