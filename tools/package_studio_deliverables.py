#!/usr/bin/env python3
"""Create a high-level AI design report and distributable ZIP for a Studio experience."""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate


def load_json(path: Path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, json.JSONDecodeError):
        return default


def paragraphs_for_report(args, output_dir: Path, summary: str):
    safe = lambda value: escape(str(value))
    plan = load_json(args.map, {})
    cast = load_json(args.cast, [])
    research = load_json(args.research, [])
    props = plan.get("props", []) if isinstance(plan, dict) else []
    shots = plan.get("camera_shots", []) if isinstance(plan, dict) else []
    names = [str(prop.get("name", "Unnamed Part")) for prop in props[:30] if isinstance(prop, dict)]
    research_items = research if isinstance(research, list) else []
    research_lines = []
    for item in research_items[:8]:
        if isinstance(item, dict):
            title = item.get("title") or item.get("source") or item.get("url") or "Reference"
            url = item.get("url", "")
            research_lines.append(f"{title}{(' — ' + url) if url else ''}")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], textColor=colors.HexColor("#17324d"), spaceAfter=14))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#126782"), spaceBefore=12, spaceAfter=5))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], leading=14, alignment=TA_LEFT, spaceAfter=6))
    story = [Paragraph("AI Roblox Short Build Report", styles["ReportTitle"])]
    story += [Paragraph(f"<b>World:</b> {safe(plan.get('name', 'Untitled world'))}", styles["BodyCustom"]),
              Paragraph(f"<b>Prompt theme:</b> {safe(plan.get('theme', 'Not specified'))}", styles["BodyCustom"]),
              Paragraph(f"<b>Duration:</b> {args.duration} seconds &nbsp;&nbsp; <b>AI map Parts:</b> {len(props)} &nbsp;&nbsp; <b>Camera shots:</b> {len(shots)}", styles["BodyCustom"]),
              Paragraph(f"<b>AI model:</b> {safe(args.model)}", styles["BodyCustom"]),
              Paragraph(f"<b>Voice:</b> {safe(args.voice)}; speech rate {safe(args.rate)}", styles["BodyCustom"])]
    story += [Paragraph("AI-generated creation summary", styles["Section"]),
              Paragraph(summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>"), styles["BodyCustom"])]
    story += [Paragraph("Design choices and deliverables", styles["Section"]),
              Paragraph("The final map and camera plan follow the user-provided theme when present, and use story context only when no theme was supplied. The optional Studio world contains editable Roblox Parts already in Workspace. The MP4 uses authentic Roblox avatars for the required usernames, preferring public 3D meshes and falling back only to that account's genuine Roblox avatar thumbnail if mesh access is denied; no AI-generated character substitutes are used.", styles["BodyCustom"]),
              Paragraph(f"<b>Cast usernames:</b> {safe(', '.join(map(str, cast)) if cast else 'The current Roblox Player avatar')}", styles["BodyCustom"]),
              Paragraph("<b>Representative authored Parts:</b> " + safe(", ".join(names) if names else "None listed"), styles["BodyCustom"])]
    story += [Paragraph("Tools used", styles["Section"]),
              Paragraph(f"1. Ollama with {safe(args.model)}: story/world/camera planning and the final high-level creation summary.<br/>2. ddgs web search: optional story-background references when available.<br/>3. edge-tts ({safe(args.voice)}, {safe(args.rate)}): slower narration audio and timed SRT subtitles.<br/>4. Roblox public avatar APIs: retrieve authentic usernames' OBJ/MTL meshes and textures when available, or their genuine account avatar thumbnails when mesh access is unavailable.<br/>5. Three.js and headless Chromium: render the furnished 3D scene and burn the readable caption HUD into every frame.<br/>6. FFmpeg: encode the 1440x2560 H.264/AAC MP4 and validate playback.<br/>7. Python map validator, Roblox XML serializer, ReportLab, and zipfile: validation, optional editable Studio place, PDF, and ZIP.", styles["BodyCustom"])]
    if research_lines:
        story += [Paragraph("Optional research references", styles["Section"])]
        story.extend(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), styles["BodyCustom"]) for line in research_lines)
    story += [Paragraph("Checks and limitations", styles["Section"]),
              Paragraph("The workflow builds a vertical MP4 automatically with headless Three.js, Chromium, and FFmpeg; it does not require Roblox Studio or Blender. It verifies the H.264/AAC video, duration, frame size/rate, subtitle cues, and public Roblox avatar mesh or authentic account-thumbnail files. The optional .rbxlx project is packaged for Studio, but the MP4 is rendered from the same AI-authored world using a real-time 3D renderer, not captured from a running Roblox client. Roblox's platform and model output budget impose practical limits; there is no fixed 100-Part cap in the map validator.", styles["BodyCustom"]),
              Paragraph("Reasoning note: this report contains a concise summary of the final design and the tools used, not private internal chain-of-thought.", styles["BodyCustom"])]
    return story


def create_pdf(args, output_dir: Path, summary: str):
    output = output_dir / "AI_Design_and_Tools_Report.pdf"
    doc = SimpleDocTemplate(str(output), pagesize=letter, rightMargin=0.65 * inch,
                            leftMargin=0.65 * inch, topMargin=0.65 * inch, bottomMargin=0.65 * inch,
                            title="AI Roblox Short Build Report", author="Roblox Short Generator")
    doc.build(paragraphs_for_report(args, output_dir, summary))
    return output


def create_zip(output_dir: Path):
    archive = output_dir / "Roblox_Studio_Complete_Package.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path != archive and path.name != "short_silent.mp4":
                bundle.write(path, path.relative_to(output_dir))
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--cast", type=Path, required=True)
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", default="-8%")
    parser.add_argument("--duration", type=int, required=True)
    args = parser.parse_args()
    output_dir = args.directory
    summary = args.summary.read_text(encoding="utf-8").strip()
    if not summary:
        raise SystemExit("AI creation summary is empty; refusing to package an incomplete report.")
    pdf = create_pdf(args, output_dir, summary)
    archive = create_zip(output_dir)
    print(f"Created {pdf} and {archive} with {len(load_json(args.map, {}).get('props', []))} AI-authored map Parts.")


if __name__ == "__main__":
    main()
