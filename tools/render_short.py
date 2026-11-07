#!/usr/bin/env python3
"""Render a vertical 2K Roblox-style 3D short in Blender from the generated plans."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import DURATIONS  # noqa: E402

import bpy
from mathutils import Vector


SKIN = (0.78, 0.57, 0.39, 1.0)
SHIRT = (0.08, 0.32, 0.88, 1.0)
PANTS = (0.08, 0.11, 0.19, 1.0)
HAIR = (0.12, 0.065, 0.035, 1.0)
FACE_DARK = (0.025, 0.018, 0.025, 1.0)


def args_from_blender():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--animation", required=True)
    parser.add_argument("--map", required=True)
    parser.add_argument("--characters", help="JSON array of Roblox usernames for the cast", default="")
    parser.add_argument("--profiles", help="JSON array of public avatar model profiles", default="")
    parser.add_argument("--duration", type=int, choices=DURATIONS, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=30)
    return parser.parse_args(argv)


def rgb_color(color):
    return tuple(float(channel) / 255.0 for channel in color) + (1.0,)


def make_material(name, color):
    mat = bpy.data.materials.new(name=name)
    mat.diffuse_color = color
    return mat


def local_empty(name, parent=None, position=(0, 0, 0)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.empty_display_type = "SPHERE"
    obj.empty_display_size = 0.08
    obj.parent = parent
    obj.location = position
    return obj


def make_primitive(name, shape, dimensions, material, parent=None, position=(0, 0, 0)):
    if shape == "Ball":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=1)
        obj = bpy.context.object
        obj.scale = tuple(float(d) / 2 for d in dimensions)
    elif shape == "Cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1)
        obj = bpy.context.object
        obj.scale = dimensions
    else:
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.object
        obj.scale = dimensions
    obj.name = name
    obj.parent = parent
    obj.location = position
    if material:
        obj.data.materials.clear()
        obj.data.materials.append(material)
    return obj


def roblox_to_blender(vector):
    # Roblox: X right, Y up, Z depth. Blender scene: Z up, front is -Y.
    x, y, z = vector
    return (float(x), -float(z), float(y))


def add_world_map(plan):
    ground = make_material("Map Ground", rgb_color(plan["ground_color"]))
    asphalt = make_material("Road Asphalt", (0.11, 0.12, 0.15, 1))
    sidewalk = make_material("Pale Concrete", (0.65, 0.68, 0.72, 1))
    lane = make_material("Warm Road Marking", (1.0, 0.76, 0.28, 1))
    make_primitive("Ground Platform", "Block", (180, 180, 2), ground, position=(0, 0, -1))
    make_primitive("Central Avenue", "Block", (14, 150, 0.14), asphalt, position=(0, 0, 0.08))
    make_primitive("West Sidewalk", "Block", (7, 150, 0.18), sidewalk, position=(-10.5, 0, 0.1))
    make_primitive("East Sidewalk", "Block", (7, 150, 0.18), sidewalk, position=(10.5, 0, 0.1))
    for y in range(-68, 69, 14):
        make_primitive("Dashed Lane Marking", "Block", (0.45, 5, 0.08), lane, position=(0, -y, 0.2))
    for index, prop in enumerate(plan["props"]):
        mat = make_material(f"Story Prop {index + 1} - {prop['name']}", rgb_color(prop["color"]))
        pos = roblox_to_blender(prop["position"])
        sx, sy, sz = prop["size"]
        dimensions = (sx, sz, sy)
        make_primitive(prop["name"], prop["shape"], dimensions, mat, position=pos)


def create_avatar_name_tag(label, parent, height, variant, front_local=(0, -1)):
    name_material = make_material(f"Roblox Name Tag {variant + 1}", (0.96, 0.97, 1.0, 1.0))
    name_curve = bpy.data.curves.new(f"Roblox Name Tag Text {variant + 1}", type="FONT")
    name_curve.body = label[:20]
    name_curve.align_x = "CENTER"
    name_curve.size = 0.30
    name_obj = bpy.data.objects.new(f"Roblox Name Tag {variant + 1}", name_curve)
    bpy.context.collection.objects.link(name_obj)
    name_obj.parent = parent
    front_length = math.hypot(float(front_local[0]), float(front_local[1])) or 1.0
    front_x, front_y = float(front_local[0]) / front_length, float(front_local[1]) / front_length
    name_obj.location = (front_x * 0.44, front_y * 0.44, height / 2 + 0.28)
    name_obj.rotation_euler = (math.radians(90), 0, math.atan2(front_x, -front_y))
    name_obj.data.materials.append(name_material)
    return name_obj


def import_avatar_model(username, profile, position, variant):
    obj_path = Path(profile.get("model_obj", ""))
    if not profile.get("model_ready") or not obj_path.is_file():
        raise RuntimeError(f"Actual Roblox avatar mesh is missing for {username}")
    before = set(bpy.data.objects)
    if not hasattr(bpy.ops.wm, "obj_import"):
        try:
            bpy.ops.preferences.addon_enable(module="io_scene_obj")
        except Exception:
            pass
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=str(obj_path), forward_axis="NEGATIVE_Z", up_axis="Y",
                              use_split_objects=True, use_split_groups=True)
    elif hasattr(bpy.ops.import_scene, "obj"):
        bpy.ops.import_scene.obj(filepath=str(obj_path), axis_forward="-Z", axis_up="Y",
                                 use_split_objects=True, use_split_groups=True)
    else:
        raise RuntimeError("This Blender build does not provide a usable OBJ importer")
    imported = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if not imported:
        imported = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not imported:
        raise RuntimeError(f"Roblox avatar OBJ imported no mesh for {username}")

    bpy.ops.object.select_all(action="DESELECT")
    for obj in imported:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = imported[0]
    bpy.ops.object.join()
    avatar = bpy.context.object
    avatar.name = f"RobloxAvatar_{variant + 1}_{username[:20]}"
    avatar.data.name = f"RobloxAvatarMesh_{variant + 1}"

    image_nodes = []
    for material in avatar.data.materials:
        if not material:
            continue
        color = list(material.diffuse_color)
        if len(color) == 4:
            color[3] = 1.0
            material.diffuse_color = color
        if material.node_tree:
            for node in material.node_tree.nodes:
                node.select = False
                if node.type == "TEX_IMAGE" and node.image:
                    node.select = True
                    material.node_tree.nodes.active = node
                    image_nodes.append(node)
                if node.type == "BSDF_PRINCIPLED" and "Alpha" in node.inputs:
                    node.inputs["Alpha"].default_value = 1.0
    if profile.get("texture_count", 0) and not image_nodes:
        raise RuntimeError(f"Roblox avatar textures failed to load for {username}")
    for node in image_nodes:
        if node.image and node.image.filepath and not node.image.packed_file:
            image_path = Path(bpy.path.abspath(node.image.filepath))
            if not image_path.is_file():
                raise RuntimeError(f"Roblox avatar texture file is missing for {username}: {image_path}")

    bpy.context.view_layer.objects.active = avatar
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    bpy.context.view_layer.update()
    original_height = float(avatar.dimensions.z)
    if original_height <= 0.01:
        raise RuntimeError(f"Roblox avatar mesh has invalid dimensions for {username}")
    scale = 4.0 / original_height
    avatar.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    x, floor_offset, z = position
    avatar.location = (float(x), float(floor_offset), float(z) + float(avatar.dimensions.z) / 2)

    front = profile.get("front_direction", [0, 0, 1])
    front_blender = roblox_to_blender(front)
    if math.hypot(front_blender[0], front_blender[1]) > 1e-5:
        avatar.rotation_euler.z = math.atan2(-1.0, 0.0) - math.atan2(front_blender[1], front_blender[0])
    create_avatar_name_tag(username, avatar, float(avatar.dimensions.z), variant,
                           (front_blender[0], front_blender[1]))
    print(f"Imported actual full-body Roblox avatar mesh for {username}")
    return avatar


def avatar_motion(animation, avatar, fps, total_frames):
    """Apply AI-timed full-character turns, leans, and rhythmic body movement to the exact avatar mesh."""
    keyframes = animation.get("keyframes", [])
    base_location = avatar.location.copy()
    base_yaw = avatar.rotation_euler.z
    for key in keyframes:
        if not isinstance(key, dict):
            continue
        time = key.get("time", 0)
        if not isinstance(time, (int, float)):
            continue
        frame_no = max(0, min(total_frames, round(float(time) * fps)))
        poses = key.get("poses", {}) if isinstance(key.get("poses", {}), dict) else {}

        def angles(name):
            value = poses.get(name, [0, 0, 0])
            if not isinstance(value, list) or len(value) != 3:
                return (0.0, 0.0, 0.0)
            try:
                return tuple(float(v) for v in value)
            except (TypeError, ValueError):
                return (0.0, 0.0, 0.0)

        root = angles("HumanoidRootPart")
        torso = angles("UpperTorso")
        head = angles("Head")
        xrot = max(-18, min(18, root[0] + torso[0] * 0.40 + head[0] * 0.12))
        yrot = max(-18, min(18, root[1] + torso[1] * 0.35 + head[1] * 0.10))
        zrot = max(-22, min(22, root[2] + torso[2] * 0.40 + head[2] * 0.12))
        avatar.location = (base_location.x, base_location.y,
                           base_location.z + 0.045 * math.sin(float(time) * math.pi * 2 / 1.6))
        avatar.rotation_euler = (math.radians(xrot), math.radians(zrot), base_yaw - math.radians(yrot))
        avatar.keyframe_insert(data_path="location", frame=frame_no, group="Full Avatar Motion")
        avatar.keyframe_insert(data_path="rotation_euler", frame=frame_no, group="Full Avatar Motion")
    action = avatar.animation_data.action if avatar.animation_data else None
    if action:
        for curve in action.fcurves:
            for point in curve.keyframe_points:
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
                point.interpolation = "BEZIER"


def create_character(username="", position=(0, -24, 1.9), variant=0, avatar_profile=None):
    palette = [SHIRT, (0.78, 0.12, 0.16, 1), (0.12, 0.58, 0.28, 1), (0.52, 0.18, 0.78, 1), (0.95, 0.48, 0.08, 1), (0.08, 0.62, 0.68, 1)]
    key = username.casefold().encode("utf-8") if username else str(variant).encode("ascii")
    palette_index = int.from_bytes(hashlib.sha256(key).digest()[:2], "big") % len(palette)
    shirt_color = palette[palette_index]
    avatar_profile = avatar_profile or {}

    def sampled_color(key, fallback):
        value = avatar_profile.get(key)
        if isinstance(value, list) and len(value) == 3 and all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in value):
            return rgb_color(value)
        return fallback

    label = username[:20] if username else f"Story Character {variant + 1}"
    skin = make_material(f"Avatar Skin {variant + 1}", sampled_color("skin_rgb", SKIN))
    shirt = make_material(f"Avatar Shirt {variant + 1}", sampled_color("shirt_rgb", shirt_color))
    pants = make_material(f"Avatar Pants {variant + 1}", sampled_color("pants_rgb", PANTS))
    hair = make_material(f"Avatar Hair {variant + 1}", sampled_color("hair_rgb", HAIR))
    dark = make_material(f"Face Details {variant + 1}", FACE_DARK)

    root = local_empty(f"R15_Root_{variant + 1}")
    root.location = position
    lower = local_empty("LowerTorso", root)
    make_primitive("Lower Torso", "Block", (0.82, 0.48, 0.56), shirt, lower, (0, 0, 0.04))
    upper = local_empty("UpperTorso", lower, (0, 0, 0.33))
    make_primitive("Upper Torso", "Block", (0.94, 0.50, 0.68), shirt, upper, (0, 0, 0.31))

    head = local_empty("Head", upper, (0, 0, 0.68))
    make_primitive("Blocky Head", "Block", (0.76, 0.70, 0.76), skin, head, (0, 0, 0.34))
    make_primitive("Hair Cap", "Block", (0.79, 0.72, 0.23), hair, head, (0, 0.015, 0.72))
    eye_l = make_primitive("Left Eye", "Ball", (0.09, 0.035, 0.11), dark, head, (-0.17, -0.361, 0.43))
    eye_r = make_primitive("Right Eye", "Ball", (0.09, 0.035, 0.11), dark, head, (0.17, -0.361, 0.43))
    mouth = make_primitive("Animated Mouth", "Ball", (0.17, 0.035, 0.07), dark, head, (0, -0.37, 0.19))
    smile_curve = bpy.data.curves.new("Smile Curve", type="CURVE")
    smile_curve.dimensions = "3D"
    smile_curve.bevel_depth = 0.018
    smile_curve.bevel_resolution = 2
    spline = smile_curve.splines.new("POLY")
    spline.points.add(4)
    for point, xyz in zip(spline.points, [(-0.14, -0.372, 0.22, 1), (-0.08, -0.382, 0.18, 1), (0, -0.386, 0.16, 1), (0.08, -0.382, 0.18, 1), (0.14, -0.372, 0.22, 1)]):
        point.co = xyz
    smile = bpy.data.objects.new("Smile Expression", smile_curve)
    bpy.context.collection.objects.link(smile)
    smile.parent = head
    smile.location = (0, 0, 0)
    smile.data.materials.append(dark)
    smile.scale = (0.001, 0.001, 0.001)

    create_avatar_name_tag(label, root, 3.6, variant)

    joints = {"HumanoidRootPart": root, "LowerTorso": lower, "UpperTorso": upper, "Head": head}
    for side, sign, label in (("Left", -1, "L"), ("Right", 1, "R")):
        shoulder = local_empty(f"{side}UpperArm", upper, (sign * 0.53, 0, 0.48))
        make_primitive(f"{side} Upper Arm", "Block", (0.31, 0.38, 0.68), shirt, shoulder, (0, 0, -0.34))
        elbow = local_empty(f"{side}LowerArm", shoulder, (0, 0, -0.68))
        make_primitive(f"{side} Lower Arm", "Block", (0.29, 0.36, 0.62), skin, elbow, (0, 0, -0.31))
        wrist = local_empty(f"{side}Hand", elbow, (0, 0, -0.62))
        make_primitive(f"{side} Hand", "Block", (0.27, 0.30, 0.25), skin, wrist, (0, -0.015, -0.12))
        joints[f"{side}UpperArm"] = shoulder
        joints[f"{side}LowerArm"] = elbow
        joints[f"{side}Hand"] = wrist

        hip = local_empty(f"{side}UpperLeg", lower, (sign * 0.23, 0, -0.34))
        make_primitive(f"{side} Upper Leg", "Block", (0.35, 0.43, 0.70), pants, hip, (0, 0, -0.35))
        knee = local_empty(f"{side}LowerLeg", hip, (0, 0, -0.70))
        make_primitive(f"{side} Lower Leg", "Block", (0.33, 0.40, 0.65), pants, knee, (0, 0, -0.325))
        ankle = local_empty(f"{side}Foot", knee, (0, 0, -0.65))
        make_primitive(f"{side} Foot", "Block", (0.37, 0.56, 0.20), hair, ankle, (0, -0.10, -0.08))
        joints[f"{side}UpperLeg"] = hip
        joints[f"{side}LowerLeg"] = knee
        joints[f"{side}Foot"] = ankle

    return joints, {"mouth": mouth, "smile": smile, "eyes": (eye_l, eye_r)}


def animate_character(animation, joints, face_objects, fps, total_frames):
    for frame in animation["keyframes"]:
        frame_no = max(0, min(total_frames, round(frame["time"] * fps)))
        for joint, angles in frame["poses"].items():
            if joint not in joints:
                continue
            rx, ry, rz = (math.radians(float(value)) for value in angles)
            joints[joint].rotation_euler = (rx, rz, -ry)
            joints[joint].keyframe_insert(data_path="rotation_euler", frame=frame_no, group=joint)

    mouth, smile, eyes = face_objects["mouth"], face_objects["smile"], face_objects["eyes"]
    states = [(round(k["time"] * fps), k.get("face", "talk")) for k in animation["keyframes"]]
    blink_frames = [frame for frame, state in states if state == "blink"]
    state_index = 0
    current_state = "talk"
    for frame_no in range(0, total_frames + 1, 8):
        while state_index + 1 < len(states) and states[state_index + 1][0] <= frame_no:
            state_index += 1
        if states:
            current_state = states[state_index][1]
        is_blink_key = any(abs(frame_no - event) <= 4 for event in blink_frames)
        if current_state == "blink":
            current_state = "talk"
        blink = is_blink_key or (frame_no % (fps * 4) < 2)
        mouth_height = 0.08 if current_state == "shocked" else (0.065 if current_state == "talk" and (frame_no // 8) % 2 == 0 else 0.025)
        if current_state in {"neutral", "smile"}:
            mouth_height = 0.024
        mouth.scale = (0.085, 0.0175, 0.035 * (mouth_height / 0.07))
        mouth.keyframe_insert(data_path="scale", frame=frame_no)
        smile.scale = (1.0, 1.0, 1.0) if current_state == "smile" else (0.001, 0.001, 0.001)
        smile.keyframe_insert(data_path="scale", frame=frame_no)
        for eye in eyes:
            eye_scale_z = 0.004 if blink else (0.066 if current_state == "shocked" else 0.055)
            eye.scale = (0.045, 0.0175, eye_scale_z)
            eye.keyframe_insert(data_path="scale", frame=frame_no)


def supporting_animation(duration, variant):
    """Subtle, staggered idle/reaction acting for cast members without AI tracks."""
    sign = -1 if variant % 2 else 1
    return {"keyframes": [
        {"time": 0, "face": "neutral", "poses": {"Head": [0, 0, 0]}},
        {"time": duration * 0.22, "face": "talk", "poses": {"Head": [0, sign * 8, 0]}},
        {"time": duration * 0.48, "face": "shocked", "poses": {"Head": [0, -sign * 7, 0], "RightUpperArm": [-12, 0, 38]}},
        {"time": duration * 0.66, "face": "smile", "poses": {"Head": [0, sign * 5, 0], "RightUpperArm": [0, 0, 8]}},
        {"time": duration, "face": "neutral", "poses": {"Head": [0, 0, 0]}},
    ]}


def make_camera(plan, fps, total_frames, duration):
    cam_data = bpy.data.cameras.new("Story Camera")
    cam = bpy.data.objects.new("Story Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam_data.lens = 50
    cam_data.sensor_fit = "VERTICAL"
    bpy.context.scene.camera = cam
    shots = plan.get("camera_shots") or []
    if not shots:
        shots = [{"time": 0, "position": [0, 32, 76], "target": [0, 3, 24], "transition": "smooth"},
                 {"time": duration * 0.5, "position": [-10, 8, 38], "target": [0, 3, 24], "transition": "snap"},
                 {"time": duration, "position": [0, 28, 84], "target": [0, 3, 24], "transition": "smooth"}]
    def set_camera_key(shot, frame_no):
        location = Vector(roblox_to_blender(shot["position"]))
        target = Vector(roblox_to_blender(shot["target"]))
        direction = target - location
        if direction.length < 0.01:
            direction = Vector((0, 1, -0.2))
        cam.location = location
        cam.rotation_mode = "QUATERNION"
        cam.rotation_quaternion = direction.to_track_quat("-Z", "Y")
        cam.keyframe_insert(data_path="location", frame=frame_no, group="Camera Move")
        cam.keyframe_insert(data_path="rotation_quaternion", frame=frame_no, group="Camera Aim")
        cam.data.lens = 48 if shot.get("transition") == "snap" else 52
        cam.data.keyframe_insert(data_path="lens", frame=frame_no)

    snap_frames = set()
    for index, shot in enumerate(shots):
        frame_no = min(total_frames, max(0, round(float(shot["time"]) * fps)))
        if index and shot.get("transition") == "snap":
            snap_frames.add(frame_no)
            set_camera_key(shots[index - 1], max(0, frame_no - 1))
        set_camera_key(shot, frame_no)

    action = cam.animation_data.action if cam.animation_data else None
    if action:
        for curve in action.fcurves:
            for point in curve.keyframe_points:
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
                if round(point.co.x) + 1 in snap_frames:
                    point.interpolation = "CONSTANT"
                else:
                    point.interpolation = "BEZIER"
    return cam


def main():
    args = args_from_blender()
    duration = args.duration
    fps = args.fps
    total_frames = duration * fps
    animation = json.loads(Path(args.animation).read_text(encoding="utf-8"))
    map_plan = json.loads(Path(args.map).read_text(encoding="utf-8"))
    usernames = json.loads(Path(args.characters).read_text(encoding="utf-8")) if args.characters else []
    if not isinstance(usernames, list) or any(not isinstance(name, str) for name in usernames):
        raise ValueError("--characters must point to a JSON array of usernames")
    profiles = json.loads(Path(args.profiles).read_text(encoding="utf-8")) if args.profiles else []
    profiles_by_name = {item.get("username", "").casefold(): item for item in profiles if isinstance(item, dict)}
    cast = usernames or [""]
    placements = {item["username"].casefold(): item["position"]
                  for item in map_plan.get("character_placements", [])
                  if isinstance(item, dict) and isinstance(item.get("username"), str)
                  and isinstance(item.get("position"), list) and len(item["position"]) == 3}

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.background_type = "WORLD"
    try:
        aa_items = scene.display.bl_rna.properties["render_aa"].enum_items.keys()
        if "8" in aa_items:
            scene.display.render_aa = "8"
    except (AttributeError, KeyError, TypeError):
        pass
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.frame_start = 0
    scene.frame_end = total_frames
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    try:
        scene.render.ffmpeg.ffmpeg_preset = "REALTIME"
    except (AttributeError, TypeError, ValueError):
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    # `max_rate` is not exposed by Blender's FFmpegSettings in Blender 4.0.x.
    # Keep to the stable bitrate property shared by the Ubuntu Blender builds.
    scene.render.ffmpeg.video_bitrate = 6000
    scene.render.filepath = str(Path(args.output).resolve())
    scene.render.use_file_extension = True
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.world.color = rgb_color(map_plan.get("ambient_color", [135, 155, 205]))[:3]

    add_world_map(map_plan)
    default_positions = [[0, 0, 24], [-3, 0, 24], [3, 0, 24], [-6, 0, 29], [6, 0, 29], [0, 0, 34]]
    character_motions = animation.get("character_motions", {})
    for index, username in enumerate(cast[:6]):
        placement = placements.get(username.casefold()) if username else None
        roblox_position = placement or default_positions[index]
        x, y, z = roblox_position
        if index == 0:
            character_animation = {"keyframes": animation["keyframes"]}
        else:
            track = next((frames for name, frames in character_motions.items()
                          if isinstance(name, str) and name.casefold() == username.casefold()), None) if username else None
            character_animation = {"keyframes": track} if track else supporting_animation(duration, index)

        if username:
            profile = profiles_by_name.get(username.casefold(), {})
            avatar = import_avatar_model(
                username, profile, (float(x), -float(z), float(y)), index,
            )
            avatar_motion(character_animation, avatar, fps, total_frames)
        else:
            blender_position = (float(x), -float(z), 1.9 + float(y))
            joints, face = create_character("", blender_position, index)
            animate_character(character_animation, joints, face, fps, total_frames)
    make_camera(map_plan, fps, total_frames, duration)
    scene.frame_set(0)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {args.width}x{args.height} 3D short at {fps} fps for {duration} seconds")
    bpy.ops.render.render(animation=True)
    print(f"Rendered silent 3D video to {args.output}")


if __name__ == "__main__":
    main()
