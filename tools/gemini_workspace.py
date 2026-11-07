#!/usr/bin/env python3
"""The space manual the Gemini sub-agent is given when it has to change a file.

Gemini is only useful as a helper if it knows what the files in this repository
actually look like. Asked "fix the camera plan" without a reference, it invents
its own keys and the plan is rejected; asked to edit `dist/Roblox_Story_Map.json`
blind, it returns a diff or a fenced block and nothing can be written back.

So every prompt carries the rules of the *specific* files the task touches:

* the world/camera/face blueprint (`dist/Roblox_Story_Map.json`),
* the spoken narration (`dist/narration.txt`),
* the R15 animation tracks (`tools/build_roblox_animation.py` format),
* the username-matched avatar models under `users/`,
* plain Python/Lua code under `tools/`.

The manual is only as long as the task needs: the topics are picked from the
task's own `topic` field first, then from keywords in the instruction and the
target path. `python3 tools/gemini_workspace.py --task '{"kind":"edit", ...}'`
prints exactly what Gemini would be told, which is how the tests check it.

Everything here is plain text: one wrong word about a range or an enum and the
local AI's plan is rejected downstream, so the numbers below are copied from the
validators in `tools/build_story_map.py` and `tools/build_roblox_animation.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOPICS = ("map", "cameras", "faces", "narration", "animation", "models", "code")

# How to hand a file back. This part is never topic-specific.
EDIT_RULES = """\
HOW TO CHANGE FILES
When a task is about a file, you are writing that file's new contents. The
workflow overwrites the whole file with your answer, so:
- Return the complete file, never a diff, never a patch, never "…unchanged…".
- Return the bare contents only. No markdown fences, no "Sure, here is", no
  explanation before or after, no file name header.
- A .json file must stay one valid JSON document with the same top-level keys as
  the input; keep the keys you were not asked to change.
- A .py file must stay valid Python 3.11, standard library only unless the
  original file already imports something else, and must keep its `if __name__`
  block.
- Never invent a Roblox asset id, an external download, a network call, a shell
  command, or a new dependency.
- Never touch, mention or rename the cast usernames unless the task says so.
Numbers stay inside the ranges below. Out-of-range numbers are not clamped for
you on every field, so a value outside a range can throw the whole plan away."""

SPECS: dict[str, str] = {
    "map": """\
WORLD BLUEPRINT (the plan reply, and dist/Roblox_Story_Map.json after validation)
Top level keys: name, theme, ground_material, ground_color, ambient_color, props,
character_placements, camera_shots, face_expressions, search_queries.
- ground_material is one of the material names below; ground_color and
  ambient_color are [r,g,b] with each channel 0-255.
- props is the map itself: 16-28 anchors (never fewer than 8, no upper cap). Aim
  for 3-6 named building cores, 3 distinct landmarks tied to the story, and
  supporting scenery spread over the map. Not one central pile.
- Every prop is {"name","shape","material","position","size","color","physics",
  "model"}.
    name      unique across the map, letters/digits/space/_/-, 40 chars max, and
              the actual object type ("Market Hall", not "Prop 7").
    model     what the anchor IS, so the build can expand it into a furnished
              group instead of one block: building, house, shop, tower, school,
              cafe, station, temple, market, hall, library, museum, bakery,
              restaurant, clinic, workshop, cottage, castle, tree, plant, bench,
              lamp, stall, fence, rock, statue or vehicle. A model building is
              turned into walls, a stepped gable roof, glass windows and glass
              inside, a counter, tables, shelves, a rug and ceiling light, potted
              plants, plants on the window sill and vines with leaves on the
              facade. A tree becomes a trunk, branches, leaf clusters and fallen
              leaves; a plant a pot, soil and leaves; a bench a seat, back and
              legs; a stall a counter, awning, poles and produce. Always set it.
              Building anchors should be 18-40 studs wide, 10-22 tall, 16-34 deep
              so the interior has room for furniture; a tree 6-14 wide, 6-18 tall.
    shape     exactly one of: Block, Ball, Cylinder.
    material  exactly one of: Plastic, SmoothPlastic, Concrete, Grass, Slate,
              Wood, Metal, Neon, Glass, Brick, Asphalt.
    position  [x, y, z] in studs. x and z -250..250, y 0..250. y is the height of
              the part's CENTRE above the ground, so a 16-stud-tall wall sitting on
              the ground is y = 8, not 0 and not 16.
    size      [width, height, depth], each 0.5..64.
    color     [r,g,b], each 0-255. Every prop must be visible: an average darker
              than RGB 104 is lifted by the validator, so do not use near-black.
    physics   "static" or "dynamic". dynamic is only kept for a Block or Ball whose
              biggest side is 12 studs or less; everything else becomes static.
- Grid and overlap: all positions and sizes must be multiples of 0.5 (that is what
  stops faces z-fighting). Props must never intersect each other.
- The world is a 640-stud square platform: |x| + width/2 <= 320 and
  |z| + depth/2 <= 320 for every prop.
- Keep the cast lane clear so faces are never blocked: no prop with |x| < 20 while
  z is between 4 and 54.
- character_placements: one per cast username, {"username","role","position"} with
  role "lead" or "supporting" and position x/z -70..70. The lead stands near the
  centre of the action.""",
    "cameras": """\
CAMERA PLAN (camera_shots inside the same blueprint)
- 6 to 24 shots, ordered, time strictly increasing, every time between 0 and the
  run duration in seconds (never past the end, never backwards).
- Each shot: {"time","position","target","focus_username","transition",
  "framing","face_distance"}.
    position, target  [x, y, z], each value -300..300, in studs around the cast.
    focus_username    the EXACT username of one cast member, or "world". Never a
                      made-up name and never a full name - the username only.
    transition        "smooth" or "snap". "snap" is a hard cut.
    framing           "auto", "wide", "face", "close", "closeup" or "close-up".
    face_distance     how close a face shot gets, 1.6..4.0 studs (default 2.45).
- Cameras live in the air and never inside a prop: keep y at 4 or more, keep the
  camera and its target off the props you placed, and keep the target around
  chest or head height (y 3..8) for people.
- The camera follows whoever the story is about at that second: a line spoken by a
  character gets a shot whose focus_username is that character.""",
    "faces": """\
FACE TIMELINE (face_expressions inside the same blueprint)
- 6 or more beats ordered by time, each {"time","expression","intensity",
  "username"}. Time runs 0..duration and must increase.
- expression is exactly one of: neutral, happy, sad, surprised, worried, angry,
  excited, thinking.
- intensity is 0..1 (0.8 reads clearly; below 0.3 is barely visible).
- username is the exact cast username whose face changes, or "" for everyone.
- Time these beats to the words they react to. Do not switch the expression every
  half second, and do not put two beats at the same time.""",
    "narration": """\
NARRATION TEXT (dist/narration.txt)
- Only the words the narrator says: plain spoken English, one paragraph, no title,
  no headings, no speaker labels, no stage directions, no timestamps, no sound
  effects, no emoji, no quotes wrapped around the whole text.
- It must land in the requested word count. Finish the final sentence; never end on
  a half sentence and never pad toward a round number.
- No usernames, handles, gamer tags, "player", "avatar", "Roblox" or "AI" in the
  text. Characters are called by natural human first names.
- The ending is one specific moment, not a summary of the moral.""",
    "animation": """\
R15 ANIMATION TRACK (the format tools/build_roblox_animation.py validates)
Top level: {"name","looped":false,"priority":"Action","duration_seconds",
"keyframes":[...],"character_motions":{}}.
- keyframes: 12 to 80 entries, ordered, time strictly increasing from 0 up to
  duration_seconds. The first frame is at 0 and the last at the end of the short.
- Each keyframe: {"time","poses","face"}.
- poses holds R15 joint names only, each a three-number rotation in degrees
  between -180 and 180: HumanoidRootPart, LowerTorso, UpperTorso, Head,
  LeftUpperArm, LeftLowerArm, LeftHand, RightUpperArm, RightLowerArm, RightHand,
  LeftUpperLeg, LeftLowerLeg, LeftFoot, RightUpperLeg, RightLowerLeg, RightFoot.
  Omit a joint to leave it at [0,0,0]; never invent a joint or a bone.
- face is one of: neutral, talk, smile, shocked, blink.
- character_motions maps an exact cast username to its own keyframe list with the
  same rules (at least 4 frames). Only cast usernames; made-up keys are dropped.""",
    "models": """\
AVATAR MODELS (users/)
- Models are matched to usernames by file name: users/normal.obj, users/noob.glb,
  anything in OBJ, glTF, GLB, FBX, DAE, PLY, STL or 3DS, plus legacy .rbxm.
- The uploaded geometry is authentic and must be preserved: never replace a model,
  never invent a mesh, a mesh id or an asset URL, never fabricate a rig or bone.
- A model is only described or referenced by its file name; the renderer auto-rigs
  unrigged meshes itself, so do not write rigging code for them.""",
    "code": """\
CODE (tools/*.py and Lua under dist/)
- Return the whole file. Keep the module docstring, the argparse/CLI shape and the
  `if __name__ == "__main__": main()` block of the file you are editing.
- Python 3.11, standard library only unless the file already imports a package.
  No network calls, no subprocess of anything that is not already in the repo.
- Tools are called by .github/workflows/main.yml with positional paths, so never
  rename an existing argument or change the meaning of one.
- Print a short progress line to stdout so the run log shows what happened, and
  exit non-zero only on real failure.""",
}

# Keywords that pull a topic into a prompt even when the caller did not name one.
KEYWORDS = {
    "map": ("map", "prop", "prop ", "world", "blueprint", "building", "landmark",
            "stud", "scenery", "layout"),
    "cameras": ("camera", "cam ", "cam.", "shot", "framing", "close-up", "closeup",
                "zoom", "angle"),
    "faces": ("face", "expression", "facial", "emotion", "smile", "eyebrow"),
    "narration": ("narration", "narrator", "story", "voiceover", "voice-over",
                  "word count", "words", "sentence", "paragraph", "spoken"),
    "animation": ("animation", "keyframe", "pose", "rig", "walk", "jump", "gesture",
                  "r15"),
    "models": ("model", "mesh", "avatar", "obj", "glb", "gltf", "fbx", "rbxm",
               "users/"),
    "code": ("code", "script", "function", "python", "lua", "tool", "bug", "fix the",
             ".py"),
}

PATH_HINTS = (
    ("Roblox_Story_Map", ("map", "cameras", "faces")),
    ("narration", ("narration",)),
    ("animation", ("animation",)),
    ("characters", ("models",)),
)


def topics_for(task: dict) -> list[str]:
    """Which parts of the manual this task needs, in a stable order."""
    wanted: set[str] = set()
    stated = task.get("topic") or task.get("topics")
    if isinstance(stated, str):
        stated = [part.strip().lower() for part in stated.replace(",", " ").split()]
    if isinstance(stated, list):
        wanted.update(item for item in stated if item in TOPICS)
    # Only the words of the task itself: a path like dist/Roblox_Story_Map.json
    # or a run context mentioning "story" must not drag the narration rules in.
    haystack = " ".join(str(task.get(key) or "") for key in
                        ("instruction", "input")).casefold()
    for topic, words in KEYWORDS.items():
        if topic in wanted:
            continue
        if any(word in haystack for word in words):
            wanted.add(topic)
    target = str(task.get("apply_to") or "").casefold()
    for path_hint, topics in PATH_HINTS:
        if path_hint.casefold() in target:
            wanted.update(topics)
    if str(task.get("kind")) in ("edit", "code") and not wanted:
        wanted.update(("code", "map"))
    # The blueprint is the thing most edits land in, and its rules are cheap.
    if wanted & {"cameras", "faces", "map"}:
        wanted.add("map")
    return [topic for topic in TOPICS if topic in wanted]


def guide(task: dict) -> str:
    """The full reference block for one task ("" when nothing is relevant)."""
    topics = topics_for(task)
    parts = []
    if topics:
        parts.append("REFERENCE FOR THE FILES IN THIS REPOSITORY\n" + EDIT_RULES)
    for topic in topics:
        parts.append(SPECS[topic])
    return "\n\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the file manual given to Gemini.")
    parser.add_argument("--task", help="JSON object of one sub-agent task")
    parser.add_argument("--topics", help="comma separated topics to dump instead")
    args = parser.parse_args()
    if args.topics:
        for name in [part.strip() for part in args.topics.split(",") if part.strip()]:
            if name not in SPECS:
                print(f"unknown topic {name!r}; choose from {', '.join(TOPICS)}",
                      file=sys.stderr)
                return 2
            print(SPECS[name] + "\n")
        return 0
    task = json.loads(args.task) if args.task else {
        "kind": "edit", "instruction": "tidy the camera plan",
        "apply_to": "dist/Roblox_Story_Map.json"}
    text = guide(task)
    print(text or "(no file reference needed for this task)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
