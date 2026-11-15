"""Regression tests for orchestration and model-anchor name matching."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import map_orchestration as mo  # noqa: E402


class ModelAnchorNameTests(unittest.TestCase):
    def test_human_readable_labels_match_assigned_snake_case_names(self):
        props = [{"name": "Bunk Bed"}, {"name": "Nightstand with Lamp"}]
        mo._match_model_anchor_names(
            props, ["bunk_bed", "nightstand_with_lamp"])
        self.assertEqual(
            [prop["name"] for prop in props],
            ["bunk_bed", "nightstand_with_lamp"])

    def test_matching_is_case_insensitive_and_accepts_hyphens(self):
        props = [{"name": "BED-side Table"}]
        mo._match_model_anchor_names(props, ["bed_side_table"])
        self.assertEqual(props[0]["name"], "bed_side_table")

    def test_unrelated_or_missing_names_are_still_rejected(self):
        props = [{"name": "Bunk Bed"}, {"name": "Desk"}]
        with self.assertRaisesRegex(ValueError, "assigned anchor names"):
            mo._match_model_anchor_names(
                props, ["bunk_bed", "nightstand_with_lamp"])

    def test_duplicate_normalized_names_are_rejected(self):
        props = [{"name": "Bunk Bed"}, {"name": "bunk_bed"}]
        with self.assertRaisesRegex(ValueError, "unique"):
            mo._match_model_anchor_names(props, ["bunk_bed", "other_anchor"])


if __name__ == "__main__":
    unittest.main()
