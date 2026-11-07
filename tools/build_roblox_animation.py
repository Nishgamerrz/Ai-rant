#!/usr/bin/env python3
"""Validate AI-authored R15 poses and build a native Roblox KeyframeSequence model."""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import MIN_DURATION, MAX_DURATION  # noqa: E402

POSE_TREE = {
    "HumanoidRootPart": {
        "LowerTorso": {
            "UpperTorso": {
                "Head": {},
                "LeftUpperArm": {"LeftLowerArm": {"LeftHand": {}}},
                "RightUpperArm": {"RightLowerArm": {"RightHand": {}}},
            },
            "LeftUpperLeg": {"LeftLowerLeg": {"LeftFoot": {}}},
            "RightUpperLeg": {"RightLowerLeg": {"RightFoot": {}}},
        }
    }
}
JOINTS = {
    "HumanoidRootPart", "LowerTorso", "UpperTorso", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
}
FACE_STATES = {"neutral", "talk", "smile", "shocked", "blink"}


def default_animation(duration):
    """Make a varied conversational gesture fallback spanning the full requested runtime."""
    neutral = {joint: [0.0, 0.0, 0.0] for joint in JOINTS}
    poses = []
    for i, ratio in enumerate((0, .08, .16, .24, .32, .40, .48, .56, .64, .72, .80, .88, .96, 1)):
        pose = dict(neutral)
        if i % 2:
            pose["UpperTorso"] = [0, 0, (-1 if i % 4 else 1) * 7]
            pose["Head"] = [0, (-1 if i % 4 else 1) * 8, 0]
            if i % 4 == 1:
                pose["RightUpperArm"] = [-15, 0, 65]
                pose["RightLowerArm"] = [0, 0, -25]
                pose["RightHand"] = [0, 0, 10]
            else:
                pose["LeftUpperArm"] = [-15, 0, -65]
                pose["LeftLowerArm"] = [0, 0, 25]
                pose["LeftHand"] = [0, 0, -10]
        face = "smile" if i in (0, 13) else ("shocked" if i in (5, 6) else "talk")
        poses.append({"time": duration * ratio, "poses": pose, "face": face})
    return {
        "name": "AI_R15_Story_Animation",
        "looped": False,
        "priority": "Action",
        "keyframes": poses,
    }


def normalize(data, duration, allowed_usernames=(), min_keyframes=12):
    if not isinstance(data, dict):
        raise ValueError("animation must be a JSON object")
    frames = data.get("keyframes")
    if not isinstance(frames, list) or not min_keyframes <= len(frames) <= 80:
        raise ValueError(f"keyframes must contain {min_keyframes} to 80 entries")
    normalized = []
    previous = -1.0
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("each keyframe must be an object")
        time = frame.get("time")
        poses = frame.get("poses")
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time):
            raise ValueError("keyframe time must be a finite number")
        time = float(time)
        if time < 0 or time > duration or time <= previous:
            raise ValueError(f"keyframe times must increase from 0 to {duration:g} seconds")
        if not isinstance(poses, dict) or set(poses) - JOINTS:
            raise ValueError("poses must be an object using only supported R15 body-part names")
        clean_poses = {}
        for joint in JOINTS:
            angles = poses.get(joint, [0, 0, 0])
            if (not isinstance(angles, list) or len(angles) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) or abs(v) > 180 for v in angles)):
                raise ValueError(f"{joint} must have three rotation angles between -180 and 180")
            clean_poses[joint] = [float(v) for v in angles]
        face = frame.get("face", "talk")
        if not isinstance(face, str) or face.lower() not in FACE_STATES:
            face = "talk"
        normalized.append({"time": time, "poses": clean_poses, "face": face.lower()})
        previous = time
    if normalized[0]["time"] != 0:
        normalized.insert(0, {"time": 0.0, "poses": {j: [0.0, 0.0, 0.0] for j in JOINTS}, "face": "neutral"})

    # Always span the chosen short runtime. Keep generated relative timing, but stretch
    # it to the requested duration if the model returned a shorter timeline.
    end = normalized[-1]["time"]
    if end <= 0:
        raise ValueError("the last keyframe must be after time zero")
    factor = duration / end
    for frame in normalized:
        frame["time"] *= factor
    normalized[-1]["time"] = float(duration)

    name = data.get("name", "AI_R15_Story_Animation")
    if not isinstance(name, str):
        name = "AI_R15_Story_Animation"
    name = "".join(ch for ch in name if ch.isalnum() or ch in " _-")[:80].strip()
    clean_character_motions = {}
    allowed_by_key = {username.casefold(): username for username in allowed_usernames}
    raw_character_motions = data.get("character_motions", {})
    if isinstance(raw_character_motions, dict):
        for username, track_frames in list(raw_character_motions.items())[:6]:
            if not isinstance(username, str) or username.casefold() not in allowed_by_key:
                continue
            try:
                track = normalize({"keyframes": track_frames}, duration, (), 4)
                clean_character_motions[allowed_by_key[username.casefold()]] = track["keyframes"]
            except (TypeError, ValueError):
                continue
    return {
        "name": name or "AI_R15_Story_Animation",
        "looped": False,
        "priority": "Action",
        "duration_seconds": float(duration),
        "keyframes": normalized,
        "character_motions": clean_character_motions,
    }


def cframe_matrix(angles):
    x, y, z = (math.radians(a) for a in angles)
    # Same XYZ Euler composition as CFrame.Angles(rx, ry, rz): Rx * Ry * Rz.
    sx, cx = math.sin(x), math.cos(x)
    sy, cy = math.sin(y), math.cos(y)
    sz, cz = math.sin(z), math.cos(z)
    return (
        cy * cz, -cy * sz, sy,
        cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy,
        sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy,
    )


def add_property(parent, kind, name, value):
    node = ET.SubElement(parent, kind, {"name": name})
    node.text = str(value)


def add_pose(parent_item, pose_tree, poses, refs):
    for part_name, children in pose_tree.items():
        item = ET.SubElement(parent_item, "Item", {"class": "Pose", "referent": f"RBX{refs[0]}"})
        refs[0] += 1
        props = ET.SubElement(item, "Properties")
        cf = ET.SubElement(props, "CoordinateFrame", {"name": "CFrame"})
        for label, value in (("X", 0), ("Y", 0), ("Z", 0)):
            ET.SubElement(cf, label).text = str(value)
        matrix = cframe_matrix(poses[part_name])
        labels = ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
        for label, value in zip(labels, matrix):
            ET.SubElement(cf, label).text = format(value, ".9g")
        add_property(props, "float", "Weight", 1)
        add_property(props, "string", "Name", part_name)
        add_property(props, "token", "EasingStyle", 0)
        add_property(props, "token", "EasingDirection", 0)
        add_pose(item, children, poses, refs)


def create_rbxmx(animation, output):
    root = ET.Element("roblox", {"version": "4"})
    sequence = ET.SubElement(root, "Item", {"class": "KeyframeSequence", "referent": "RBX0"})
    props = ET.SubElement(sequence, "Properties")
    add_property(props, "bool", "Loop", "false")
    add_property(props, "string", "Name", animation["name"])
    add_property(props, "int64", "SourceAssetId", -1)
    add_property(props, "token", "Priority", 2)  # Enum.AnimationPriority.Action
    refs = [1]
    for index, frame in enumerate(animation["keyframes"]):
        keyframe = ET.SubElement(sequence, "Item", {"class": "Keyframe", "referent": f"RBX{refs[0]}"})
        refs[0] += 1
        key_props = ET.SubElement(keyframe, "Properties")
        add_property(key_props, "double", "Time", format(frame["time"], ".9g"))
        add_property(key_props, "string", "Name", f"Keyframe_{index:02d}")
        add_pose(keyframe, POSE_TREE, frame["poses"], refs)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("duration", type=float)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--usernames", type=Path, help="JSON file containing allowed cast usernames")
    args = parser.parse_args()
    source, destination, duration = args.source, args.destination, args.duration
    json_only = args.json_only
    usernames = json.loads(args.usernames.read_text(encoding="utf-8")) if args.usernames else []
    if not isinstance(usernames, list) or any(not isinstance(name, str) for name in usernames):
        raise SystemExit("usernames file must be a JSON array of strings")
    try:
        if not MIN_DURATION <= duration <= MAX_DURATION:
            raise ValueError(f"duration must be {MIN_DURATION} to {MAX_DURATION} seconds")
        data = json.loads(source.read_text(encoding="utf-8"))
        animation = normalize(data, duration, usernames)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid AI animation ({exc}); using generated R15 gesture keyframes.", file=sys.stderr)
        animation = normalize(default_animation(duration), duration, usernames)
    destination.parent.mkdir(parents=True, exist_ok=True)
    json_path = destination if json_only else destination.with_suffix(".json")
    if not json_only:
        create_rbxmx(animation, destination)
    json_path.write_text(json.dumps(animation, indent=2) + "\n", encoding="utf-8")
    print(f"Created animation data {json_path}: {duration:g} seconds, {len(animation['keyframes'])} R15 keyframes.")


if __name__ == "__main__":
    main()
