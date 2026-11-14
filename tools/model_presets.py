#!/usr/bin/env python3
"""Resolve a public model preset from the shared website/Actions manifest.

The JSON file is also imported by the model selector. Workflows call this helper
before cache restore/download so the displayed preset, cache key, and Ollama tag
all come from the same entry rather than parallel handwritten mappings.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "web" / "lib" / "model_presets.json"
DEFAULT_MODEL_QUALITY = "hard"


def _load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    presets = manifest.get("presets")
    if not isinstance(presets, dict) or not presets:
        raise ValueError(f"No model presets are configured in {MANIFEST_PATH}")
    for quality, preset in presets.items():
        if not isinstance(preset, dict) or not isinstance(preset.get("model"), str) or not preset["model"].strip():
            raise ValueError(f"Model preset {quality!r} has no valid Ollama model")
        if (not isinstance(preset.get("label"), str) or not preset["label"].strip()
                or not isinstance(preset.get("cache_version"), str) or not preset["cache_version"].strip()):
            raise ValueError(f"Model preset {quality!r} is missing its label or cache version")
        for field in ("minimum_gib", "timeout_seconds"):
            if not isinstance(preset.get(field), int) or preset[field] <= 0:
                raise ValueError(f"Model preset {quality!r} has an invalid {field}")
    return presets


MODEL_PRESETS = _load_manifest()
MODEL_MAP = {quality: preset["model"] for quality, preset in MODEL_PRESETS.items()}
DEFAULT_MODEL = MODEL_MAP[DEFAULT_MODEL_QUALITY]


def normalize_model_quality(value: object) -> str:
    quality = str(value or "").strip().lower()
    if quality not in MODEL_PRESETS:
        choices = ", ".join(MODEL_PRESETS)
        raise ValueError(f"Unknown model quality {quality!r}; choose one of: {choices}.")
    return quality


def resolve_model(value: object) -> str:
    """Resolve a known preset, or honor an explicit Ollama tag without fallback."""
    candidate = str(value or "").strip()
    quality = candidate.lower()
    if quality in MODEL_MAP:
        return MODEL_MAP[quality]
    if ":" in candidate:
        return candidate
    choices = ", ".join(MODEL_PRESETS)
    raise ValueError(f"Unknown model quality or Ollama model {candidate!r}; choose one of: {choices}.")


def selection_fields(quality: str) -> dict[str, Any]:
    preset = MODEL_PRESETS[quality]
    return {
        "quality": quality,
        "label": preset["label"],
        "selected_model": preset["model"],
        "cache_version": preset["cache_version"],
        "minimum_gib": preset["minimum_gib"],
        "timeout_seconds": preset["timeout_seconds"],
    }


def write_github_outputs(quality: str, output_path: str | Path) -> None:
    values = selection_fields(quality)
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def write_selection_json(quality: str, output_path: str | Path) -> None:
    fields = selection_fields(quality)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(fields, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quality", help="selected preset id, such as fast or medium")
    parser.add_argument("--github-output", help="append resolved fields to this GITHUB_OUTPUT file")
    parser.add_argument("--json-output", help="write the resolved selection as JSON to this path")
    args = parser.parse_args(argv)

    try:
        quality = normalize_model_quality(args.quality)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    preset = MODEL_PRESETS[quality]
    if args.github_output:
        write_github_outputs(quality, args.github_output)
    if args.json_output:
        write_selection_json(quality, args.json_output)
    # This is safe public status: it identifies a preset and its selected model,
    # never private reasoning or provider payloads.
    try:
        from console_style import paint

        message = paint(
            f"Model preset {preset['label']} ({quality}) resolves to Ollama model {preset['model']}",
            "success",
        )
    except ImportError:
        message = f"Model preset {preset['label']} ({quality}) resolves to Ollama model {preset['model']}"
    print(message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
