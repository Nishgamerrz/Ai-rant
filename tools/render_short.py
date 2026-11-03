#!/usr/bin/env python3
"""Render a vertical 2K Roblox-style 3D short in Blender from the generated plans."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

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
    parser.add_argument("--duration", type=int, choices=(30, 45, 60), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=2560)
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


def create_character():
    skin = make_material("Avatar Skin", SKIN)
    shirt = make_material("Avatar Shirt", SHIRT)
    pants = make_material("Avatar Pants", PANTS)
    hair = make_material("Avatar Hair", HAIR)
    dark = make_material("Face Details", FACE_DARK)

    root = local_empty("R15_Root")
    root.location = (0, -24, 1.9)
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
            # Convert Roblox Y-up Euler components into Blender's Z-up axes.
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

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.background_type = "WORLD"
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
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    # `max_rate` is not exposed by Blender's FFmpegSettings in Blender 4.0.x.
    # Keep to the stable bitrate property shared by the Ubuntu Blender builds.
    scene.render.ffmpeg.video_bitrate = 16000
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
    joints, face = create_character()
    animate_character(animation, joints, face, fps, total_frames)
    make_camera(map_plan, fps, total_frames, duration)
    scene.frame_set(0)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {args.width}x{args.height} 3D short at {fps} fps for {duration} seconds")
    bpy.ops.render.render(animation=True)
    print(f"Rendered silent 3D video to {args.output}")


if __name__ == "__main__":
    main()
