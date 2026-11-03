#!/usr/bin/env python3
"""Package an AI-designed story map as a runnable Roblox Studio place."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


def read_json(path: Path, default):
    if path is None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def parse_srt(path: Path | None):
    if not path or not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    pattern = re.compile(
        r"(?m)^\s*\d+\s*\n"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n"
        r"(.*?)(?=\n\s*\n|\Z)", re.S,
    )
    def seconds(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    out = []
    for m in pattern.finditer(text):
        out.append({
            "start": round(seconds(*m.group(1, 2, 3, 4)), 3),
            "finish": round(seconds(*m.group(5, 6, 7, 8)), 3),
            "text": re.sub(r"<[^>]+>", "", m.group(9)).strip().replace("\n", " "),
        })
    return [item for item in out if item["text"]]


def fallback_captions(narration: str, duration: float):
    """Create readable, evenly timed caption cues when a subtitle sidecar is missing or invalid."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", narration.strip()) if part.strip()]
    if not sentences and narration.strip():
        sentences = [narration.strip()]
    if not sentences:
        return []
    # Keep each on-screen cue short enough to read, without dropping any spoken words.
    chunks, current = [], []
    for sentence in sentences:
        words = sentence.split()
        while words:
            remaining = 16 - len(current)
            current.extend(words[:remaining])
            words = words[remaining:]
            if len(current) >= 16:
                chunks.append(" ".join(current))
                current = []
        if current and current[-1].endswith((".", "!", "?")):
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total = sum(weights)
    cursor, cues = 0.0, []
    for chunk, weight in zip(chunks, weights):
        finish = min(float(duration), cursor + float(duration) * weight / total)
        cues.append({"start": round(cursor, 3), "finish": round(finish, 3), "text": chunk})
        cursor = finish
    return cues


def long_bracket(value: str) -> str:
    equals = ""
    while f"]{equals}]" in value:
        equals += "="
    return f"[{equals}[{value}]{equals}]"


def make_config(plan, cast, duration, narration, captions, audio_asset_id):
    return {
        "plan": plan,
        "cast": cast,
        "duration": duration,
        "narration": narration,
        "captions": captions or fallback_captions(narration, duration),
        "audio_asset_id": audio_asset_id,
    }


def server_lua(config_json: str) -> str:
    cfg = long_bracket(config_json)
    source = r'''-- Generated Roblox Studio runtime setup. The complete map is already present in Workspace.
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local Lighting = game:GetService("Lighting")
local Workspace = game:GetService("Workspace")
local CONFIG = HttpService:JSONDecode(__CONFIG_JSON__)
local plan = CONFIG.plan
local map = Workspace:WaitForChild("GeneratedStoryMap")
local castFolder = map:FindFirstChild("GeneratedCast") or Instance.new("Folder")
castFolder.Name = "GeneratedCast"
castFolder.Parent = map

-- Bright, readable daylight and Roblox's own built-in sky textures prevent a black sky.
Lighting.ClockTime = 14
Lighting.Brightness = 3
Lighting.ExposureCompensation = 0.05
Lighting.GlobalShadows = true
Lighting.ShadowSoftness = 0.25
local ambient = plan.ambient_color or {175, 185, 205}
Lighting.Ambient = Color3.fromRGB(ambient[1], ambient[2], ambient[3])
Lighting.OutdoorAmbient = Color3.fromRGB(math.max(ambient[1], 150), math.max(ambient[2], 160), math.max(ambient[3], 175))
Lighting.EnvironmentDiffuseScale = 0.45
Lighting.EnvironmentSpecularScale = 0.3
local sky = Lighting:FindFirstChildOfClass("Sky") or Instance.new("Sky")
sky.Name = "GeneratedSunnySky"
sky.SkyboxBk = "rbxasset://textures/sky/sky512_bk.tex"
sky.SkyboxDn = "rbxasset://textures/sky/sky512_dn.tex"
sky.SkyboxFt = "rbxasset://textures/sky/sky512_ft.tex"
sky.SkyboxLf = "rbxasset://textures/sky/sky512_lf.tex"
sky.SkyboxRt = "rbxasset://textures/sky/sky512_rt.tex"
sky.SkyboxUp = "rbxasset://textures/sky/sky512_up.tex"
sky.CelestialBodiesShown = true
sky.StarCount = 0
sky.Parent = Lighting
local atmosphere = Lighting:FindFirstChildOfClass("Atmosphere") or Instance.new("Atmosphere")
atmosphere.Density = 0.2
atmosphere.Offset = 0.1
atmosphere.Color = Color3.fromRGB(199, 226, 255)
atmosphere.Decay = Color3.fromRGB(115, 158, 205)
atmosphere.Haze = 0.45
atmosphere.Glare = 0.08
atmosphere.Parent = Lighting

-- Add readable lettering and small point lights to the map's authored 3D signs and lamps.
for _, object in ipairs(map:GetDescendants()) do
    if object:IsA("BasePart") then
        local text = string.match(object.Name, "^Shop Sign %- (.+)$")
        if object.Name == "World Title Sign" then
            text = string.upper(plan.name or "AI STORY WORLD") .. "\n" .. (plan.theme or "")
        end
        if text then
            local surface = Instance.new("SurfaceGui")
            surface.Name = "MapSign"
            surface.Face = Enum.NormalId.Back
            surface.PixelsPerStud = 45
            surface.Parent = object
            local label = Instance.new("TextLabel")
            label.Size = UDim2.fromScale(1, 1)
            label.BackgroundTransparency = 1
            label.Text = text
            label.TextColor3 = Color3.fromRGB(255, 255, 255)
            label.TextScaled = true
            label.TextWrapped = true
            label.Font = Enum.Font.GothamBold
            label.Parent = surface
        end
        if object.Name == "Warm Street Lamp" then
            local light = Instance.new("PointLight")
            light.Color = Color3.fromRGB(255, 232, 170)
            light.Brightness = 0.7
            light.Range = 16
            light.Parent = object
        end
    end
end

-- Use the live public Roblox account appearance at runtime, not a blocky approximation.
for _, castMember in ipairs(CONFIG.cast or {}) do
    task.spawn(function()
        local ok, result = pcall(function()
            local userId = Players:GetUserIdFromNameAsync(castMember.username)
            local avatar = Players:CreateHumanoidModelFromUserIdAsync(userId)
            avatar.Name = castMember.username
            local humanoid = avatar:FindFirstChildOfClass("Humanoid")
            if humanoid then
                humanoid.DisplayName = castMember.username .. (castMember.role == "lead" and " • Lead" or "")
                humanoid.WalkSpeed = 0
                humanoid.JumpPower = 0
                humanoid.AutoRotate = false
            end
            for _, descendant in ipairs(avatar:GetDescendants()) do
                if descendant:IsA("BasePart") then descendant.CanCollide = false end
            end
            local root = avatar:FindFirstChild("HumanoidRootPart")
            if root then root.Anchored = true end
            local p = castMember.position
            avatar:PivotTo(CFrame.new(p[1], p[2] + 3, p[3]))
            avatar.Parent = castFolder
            return avatar
        end)
        if not ok then
            warn("Could not load Roblox avatar for " .. castMember.username .. ": " .. tostring(result))
        end
    end)
end
print(string.format("Ready: '%s', %d AI-authored map pieces, %d live avatar(s).",
    plan.name or "AI Story World", #map:GetDescendants(), #(CONFIG.cast or {})))
'''
    return source.replace("__CONFIG_JSON__", cfg)


def build_scene_parts(plan, cast):
    """Create detailed editable Roblox Part geometry; theme-specific pieces come from the AI plan."""
    parts = []

    def add(name, size, position, color, material="Plastic", shape="Block", yaw=0, transparency=0, collidable=True):
        parts.append({
            "name": str(name), "size": list(size), "position": list(position), "color": list(color),
            "material": material, "shape": shape, "yaw": float(yaw),
            "transparency": float(transparency), "collidable": bool(collidable),
        })

    # One theme-colored walkable foundation; roads, terrain, landmarks, and decoration are AI-authored.
    add("World Foundation", (640, 2, 640), (0, -1.1, 0), plan.get("ground_color", [88, 166, 91]), plan.get("ground_material", "Grass"))
    add("World Title Sign", (30, 7, 0.6), (0, 10, 74), [35, 48, 72], "SmoothPlastic")

    # Each AI-authored object becomes a named, editable Roblox Part.
    for index, prop in enumerate(plan.get("props", []), 1):
        add(prop.get("name", f"AI Landmark {index}"), prop["size"], prop["position"],
            prop.get("color", [135, 165, 205]), prop.get("material", "Plastic"), prop.get("shape", "Block"))

    # Make AI landmarks readable at Roblox scale with small facade details around the generated layout.
    for index, prop in enumerate(plan.get("props", []), 1):
        name = prop.get("name", f"Landmark {index}").casefold()
        x, _, z = prop["position"]
        sx, sy, sz = prop["size"]
        if any(word in name for word in ("building", "shop", "tower", "house", "school", "cafe", "store", "station", "temple", "castle", "museum", "hall", "market", "hotel", "factory", "arcade", "bakery", "library", "hospital", "restaurant", "office", "apartment", "mansion", "workshop", "palace", "warehouse")):
            accent = prop.get("color", [120, 160, 210])
            add(f"{prop.get('name','Landmark')} Roof Detail", (sx * 1.06, max(0.6, min(2.5, sy * 0.08)), sz * 1.06),
                (x, prop["position"][1] + sy / 2 + 0.5, z), [min(255, c + 22) for c in accent], "SmoothPlastic")
            front_z = z + sz / 2 + 0.06
            panel_w = max(1.5, min(sx * 0.28, 9))
            panel_h = max(1.5, min(sy * 0.32, 8))
            door_y = prop["position"][1] - sy / 2 + panel_h / 2
            add(f"{prop.get('name','Landmark')} Door", (panel_w * 0.55, panel_h, 0.18),
                (x, door_y, front_z), [80, 110, 135], "Glass", transparency=0.12)
            for side in (-1, 1):
                add(f"{prop.get('name','Landmark')} Window", (panel_w, panel_h * 0.65, 0.16),
                    (x + side * sx * 0.28, prop["position"][1], front_z), [140, 218, 235], "Glass", transparency=0.18, collidable=False)
        if any(word in name for word in ("tree", "forest", "grove", "garden", "park")):
            for dx, dz in ((-5, -4), (5, -3), (-3, 6), (6, 5)):
                tx, tz = max(-215, min(215, x + dx)), max(-215, min(215, z + dz))
                add(f"{prop.get('name','Greenery')} Trunk", (2.4, 7, 2.4), (tx, 3.5, tz), [123, 82, 52], "Wood", "Cylinder")
                add(f"{prop.get('name','Greenery')} Canopy", (8, 8, 8), (tx, 9, tz), [65, 170, 95], "Grass", "Ball")

    # The lead is the real Roblox Player character spawned by Roblox, never an AI-built block rig.
    return parts


def vector3_element(name, values):
    x, y, z = values
    return (f'<Vector3 name="{name}"><X>{x}</X><Y>{y}</Y><Z>{z}</Z></Vector3>')


def color3_element(name, values):
    channels = [min(1.0, max(0.0, float(v) / 255.0)) for v in values]
    return (f'<Color3 name="{name}"><R>{channels[0]:.8g}</R>'
            f'<G>{channels[1]:.8g}</G><B>{channels[2]:.8g}</B></Color3>')


def cframe_element(name, position, yaw=0):
    import math
    theta = math.radians(yaw)
    c, s = math.cos(theta), math.sin(theta)
    r = (c, 0, s, 0, 1, 0, -s, 0, c)
    labels = ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
    return (f'<CoordinateFrame name="{name}"><X>{position[0]}</X><Y>{position[1]}</Y><Z>{position[2]}</Z>'
            + "".join(f"<{label}>{value:.9g}</{label}>" for label, value in zip(labels, r))
            + "</CoordinateFrame>")


def part_instance(part, referent):
    materials = {"Plastic": 256, "SmoothPlastic": 272, "Neon": 288, "Grass": 1280,
                 "Wood": 512, "Metal": 1088, "Concrete": 816, "Brick": 848,
                 "Glass": 1568, "Asphalt": 1376, "Slate": 800}
    shapes = {"Ball": 0, "Block": 1, "Cylinder": 2}
    props = [
        '<bool name="Anchored">true</bool>',
        f'<bool name="CanCollide">{str(part.get("collidable", True)).lower()}</bool>',
        '<bool name="CastShadow">true</bool>',
        color3_element("Color", part["color"]),
        cframe_element("CFrame", part["position"], part.get("yaw", 0)),
        f'<token name="Material">{materials.get(part.get("material"), 256)}</token>',
        xml_string("Name", part["name"]),
        f'<float name="Reflectance">0</float>',
        f'<float name="Transparency">{part.get("transparency", 0)}</float>',
        f'<token name="shape">{shapes.get(part.get("shape"), 1)}</token>',
        vector3_element("size", part["size"]),
    ]
    return item("Part", referent, props)

def client_lua(config_json: str) -> str:
    cfg = long_bracket(config_json)
    source = '''-- Opens with a captioned AI-directed camera tour, then returns control to the player.
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local CONFIG = HttpService:JSONDecode(__CONFIG_JSON__)
local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")
local gui = Instance.new("ScreenGui")
gui.Name = "GeneratedStoryHUD"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.DisplayOrder = 100
gui.Parent = playerGui
local header = Instance.new("TextLabel")
header.Name = "StoryTitle"
header.AnchorPoint = Vector2.new(0.5, 0)
header.Position = UDim2.new(0.5, 0, 0.035, 0)
header.Size = UDim2.new(0.82, 0, 0, 58)
header.BackgroundColor3 = Color3.fromRGB(18, 31, 50)
header.BackgroundTransparency = 0.18
header.TextColor3 = Color3.fromRGB(255, 231, 160)
header.Text = string.upper(CONFIG.plan.name or "AI STORY WORLD")
header.TextScaled = true
header.Font = Enum.Font.GothamBold
header.Parent = gui
local corner = Instance.new("UICorner")
corner.CornerRadius = UDim.new(0, 14)
corner.Parent = header
local caption = Instance.new("TextLabel")
caption.Name = "NarrationCaption"
caption.AnchorPoint = Vector2.new(0.5, 1)
caption.Position = UDim2.new(0.5, 0, 0.93, 0)
caption.Size = UDim2.new(0.92, 0, 0, 132)
caption.BackgroundColor3 = Color3.fromRGB(8, 14, 24)
caption.BackgroundTransparency = 0.04
caption.TextColor3 = Color3.fromRGB(255, 255, 255)
caption.TextStrokeTransparency = 0.55
caption.TextWrapped = true
caption.TextScaled = true
caption.TextTransparency = 0
caption.TextXAlignment = Enum.TextXAlignment.Center
caption.TextYAlignment = Enum.TextYAlignment.Center
caption.Visible = true
caption.ZIndex = 20
caption.Font = Enum.Font.GothamBold
caption.Parent = gui
local captionCorner = Instance.new("UICorner")
captionCorner.CornerRadius = UDim.new(0, 16)
captionCorner.Parent = caption
local skip = Instance.new("TextLabel")
skip.Name = "SkipHint"
skip.AnchorPoint = Vector2.new(1, 1)
skip.Position = UDim2.new(0.97, 0, 0.97, 0)
skip.Size = UDim2.new(0, 250, 0, 32)
skip.BackgroundTransparency = 1
skip.TextColor3 = Color3.fromRGB(245, 245, 245)
skip.Text = "SPACE  •  skip tour and explore"
skip.TextScaled = true
skip.Font = Enum.Font.Gotham
skip.Parent = gui

local soundId = CONFIG.audio_asset_id or ""
local narrationSound = nil
if soundId ~= "" then
    if string.match(soundId, "^%d+$") then soundId = "rbxassetid://" .. soundId end
    narrationSound = Instance.new("Sound")
    narrationSound.Name = "StoryNarration"
    narrationSound.SoundId = soundId
    narrationSound.Volume = 1
    narrationSound.Parent = game:GetService("SoundService")
end

local skipped = false
local inputConnection = UserInputService.InputBegan:Connect(function(input, processed)
    if not processed and input.KeyCode == Enum.KeyCode.Space then skipped = true end
end)
local worldModel = workspace:WaitForChild("GeneratedStoryMap", 90)
-- Account avatars are authentic Roblox rigs. No AI-generated body animation is applied.
local camera = workspace.CurrentCamera
local shots = CONFIG.plan.camera_shots or {{}}
local captions = CONFIG.captions or {{}}
local startTime = os.clock()
if narrationSound then narrationSound:Play() end
local duration = CONFIG.duration or 60
local previousIndex = 1
local connection
connection = RunService.RenderStepped:Connect(function()
    local elapsed = narrationSound and narrationSound.IsPlaying
        and narrationSound.TimePosition or (os.clock() - startTime)
    if skipped or elapsed >= duration then
        connection:Disconnect()
        inputConnection:Disconnect()
        camera.CameraType = Enum.CameraType.Custom
        caption.Visible = false
        skip.Visible = false
        return
    end
    local currentCaption = ""
    for _, line in ipairs(captions) do
        if elapsed >= line.start and elapsed <= line.finish then currentCaption = line.text; break end
    end
    caption.Text = currentCaption
    if #shots > 0 then
        local index = 1
        for i = 1, #shots do
            if elapsed >= shots[i].time then index = i else break end
        end
        local a = shots[index]
        local b = shots[math.min(index + 1, #shots)]
        local alpha = 0
        if b and b ~= a and b.transition ~= "snap" then
            alpha = math.clamp((elapsed - a.time) / math.max(0.01, b.time - a.time), 0, 1)
            alpha = alpha * alpha * (3 - 2 * alpha)
        end
        local posA = Vector3.new(a.position[1], a.position[2], a.position[3])
        local targetA = Vector3.new(a.target[1], a.target[2], a.target[3])
        local pos = posA
        local target = targetA
        if b and b ~= a and b.transition ~= "snap" then
            pos = posA:Lerp(Vector3.new(b.position[1], b.position[2], b.position[3]), alpha)
            target = targetA:Lerp(Vector3.new(b.target[1], b.target[2], b.target[3]), alpha)
        elseif previousIndex ~= index then
            previousIndex = index
        end
        camera.CameraType = Enum.CameraType.Scriptable
        camera.CFrame = CFrame.lookAt(pos, target)
    end
end)
'''
    return source.replace("__CONFIG_JSON__", cfg).replace("{{", "{").replace("}}", "}")


def item(class_name: str, referent: str, properties: list[str], children: str = "") -> str:
    properties = sorted(properties, key=lambda value: re.search(r'name="([^"]+)"', value).group(1))
    property_block = "\n    ".join(properties)
    return (f'<Item class="{class_name}" referent="{referent}">\n'
            f'  <Properties>\n    {property_block}\n  </Properties>\n'
            f'{children}</Item>')


def xml_string(name: str, value: str) -> str:
    return f'<string name="{name}">{html.escape(value, quote=False)}</string>'


def camera_cframe(position, target):
    import math
    direction = [target[i] - position[i] for i in range(3)]
    length = math.sqrt(sum(value * value for value in direction)) or 1
    look = [value / length for value in direction]
    up = [0.0, 1.0, 0.0]
    right = [look[1] * up[2] - look[2] * up[1],
             look[2] * up[0] - look[0] * up[2],
             look[0] * up[1] - look[1] * up[0]]
    length = math.sqrt(sum(value * value for value in right)) or 1
    right = [value / length for value in right]
    real_up = [right[1] * look[2] - right[2] * look[1],
               right[2] * look[0] - right[0] * look[2],
               right[0] * look[1] - right[1] * look[0]]
    back = [-value for value in look]
    rows = (right[0], real_up[0], back[0], right[1], real_up[1], back[1], right[2], real_up[2], back[2])
    labels = ("R00", "R01", "R02", "R10", "R11", "R12", "R20", "R21", "R22")
    return (f'<CoordinateFrame name="CFrame"><X>{position[0]}</X><Y>{position[1]}</Y><Z>{position[2]}</Z>'
            + "".join(f"<{label}>{value:.9g}</{label}>" for label, value in zip(labels, rows))
            + "</CoordinateFrame>")


def make_place(server_script: str, local_script: str, plan, cast) -> str:
    import uuid

    def ref():
        return "RBX" + uuid.uuid4().hex.upper()

    camera_ref = ref()
    camera_position = [0, 78, 175]
    camera_target = [0, 3, 0]
    camera = item("Camera", camera_ref, [
        camera_cframe(camera_position, camera_target),
        '<token name="CameraType">0</token>',
        '<float name="FieldOfView">70</float>',
        '<CoordinateFrame name="Focus"><X>0</X><Y>3</Y><Z>0</Z><R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>',
        xml_string("Name", "Camera"),
    ])

    parts = build_scene_parts(plan, cast)
    world_children = [part_instance(part, ref()) for part in parts]
    spawn_props = [
        '<bool name="Anchored">true</bool>',
        '<bool name="CanCollide">true</bool>',
        '<bool name="Enabled">true</bool>',
        cframe_element("CFrame", [0, 0.65, 28]),
        '<bool name="Neutral">true</bool>',
        xml_string("Name", "StoryWorldSpawn"),
        '<float name="Transparency">1</float>',
        '<float name="Duration">0</float>',
        vector3_element("size", [8, 1, 8]),
    ]
    world_children.append(item("SpawnLocation", ref(), spawn_props))
    world_children.append(item("Folder", ref(), [xml_string("Name", "GeneratedCast")]))
    world_model = item("Model", ref(), [xml_string("Name", "GeneratedStoryMap")], "\n".join(world_children))
    workspace = item("Workspace", ref(), [
        f'<Ref name="CurrentCamera">{camera_ref}</Ref>',
        '<float name="FallenPartsDestroyHeight">-500</float>',
        '<bool name="FilteringEnabled">true</bool>',
        '<float name="Gravity">196.2</float>',
        xml_string("Name", "Workspace"),
        '<bool name="StreamingEnabled">false</bool>',
    ], camera + world_model)

    sky_assets = ("Bk", "Dn", "Ft", "Lf", "Rt", "Up")
    sky_props = [
        '<bool name="CelestialBodiesShown">true</bool>',
        xml_string("Name", "GeneratedSunnySky"),
        '<int name="StarCount">0</int>',
    ]
    sky_props.extend(
        f'<Content name="Skybox{face}"><url>rbxasset://textures/sky/sky512_{face.lower()}.tex</url></Content>'
        for face in sky_assets
    )
    sky = item("Sky", ref(), sky_props)
    atmosphere = item("Atmosphere", ref(), [
        color3_element("Color", [199, 226, 255]),
        color3_element("Decay", [115, 158, 205]),
        '<float name="Density">0.2</float>',
        '<float name="Glare">0.08</float>',
        '<float name="Haze">0.45</float>',
        xml_string("Name", "GeneratedAtmosphere"),
        '<float name="Offset">0.1</float>',
    ])
    ambient = plan.get("ambient_color", [175, 185, 205])
    outdoor_ambient = [max(ambient[0], 150), max(ambient[1], 160), max(ambient[2], 175)]
    lighting = item("Lighting", ref(), [
        color3_element("Ambient", ambient),
        '<float name="Brightness">3</float>',
        '<float name="ClockTime">14</float>',
        '<float name="EnvironmentDiffuseScale">0.45</float>',
        '<float name="EnvironmentSpecularScale">0.3</float>',
        '<float name="ExposureCompensation">0.05</float>',
        color3_element("FogColor", [199, 226, 255]),
        '<float name="FogEnd">100000</float>',
        '<float name="FogStart">0</float>',
        '<bool name="GlobalShadows">true</bool>',
        xml_string("Name", "Lighting"),
        color3_element("OutdoorAmbient", outdoor_ambient),
        '<float name="ShadowSoftness">0.25</float>',
        '<string name="TimeOfDay">14:00:00</string>',
    ], sky + atmosphere)

    server_script_item = item("Script", ref(), [
        '<bool name="Disabled">false</bool>',
        xml_string("Name", "StoryWorldRuntime"),
        f'<ProtectedString name="Source">{html.escape(server_script, quote=False)}</ProtectedString>',
    ])
    server_service = item("ServerScriptService", ref(), [xml_string("Name", "ServerScriptService")], server_script_item)
    local_script_item = item("LocalScript", ref(), [
        '<bool name="Disabled">false</bool>',
        xml_string("Name", "StoryCameraAndCaptions"),
        f'<ProtectedString name="Source">{html.escape(local_script, quote=False)}</ProtectedString>',
    ])
    starter_scripts = item("StarterPlayerScripts", ref(), [xml_string("Name", "StarterPlayerScripts")], local_script_item)
    starter_player = item("StarterPlayer", ref(), [
        '<bool name="LoadCharacterAppearance">true</bool>',
        '<float name="CharacterWalkSpeed">16</float>',
        xml_string("Name", "StarterPlayer"),
    ], starter_scripts)
    players = item("Players", ref(), [
        '<bool name="CharacterAutoLoads">true</bool>',
        '<int name="MaxPlayersInternal">12</int>',
        xml_string("Name", "Players"),
        '<float name="RespawnTime">5</float>',
    ])
    sound_service = item("SoundService", ref(), [xml_string("Name", "SoundService")])
    services = [workspace, lighting, players, starter_player, server_service, sound_service]
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">\n'
            '<External>null</External><External>nil</External>\n'
            + "\n".join(services) + "\n</roblox>\n")

def build(args):
    plan = read_json(args.map, {})
    if not isinstance(plan, dict) or not isinstance(plan.get("props"), list):
        raise ValueError("map plan must be validated JSON with a props array")
    cast_names = read_json(args.cast, [])
    if not isinstance(cast_names, list):
        raise ValueError("cast must be a JSON array")
    placements = plan.get("character_placements", [])
    by_name = {entry.get("username", "").casefold(): entry for entry in placements if isinstance(entry, dict)}
    cast = []
    fallback_positions = [[0, 0, 24], [-3, 0, 24], [3, 0, 24], [-6, 0, 29], [6, 0, 29], [0, 0, 34]]
    for index, username in enumerate(cast_names[:6]):
        if not isinstance(username, str):
            continue
        entry = by_name.get(username.casefold(), {})
        cast.append({
            "username": username,
            "role": "lead" if index == 0 else "supporting",
            "position": entry.get("position", fallback_positions[index]),
        })
    narration = args.narration.read_text(encoding="utf-8") if args.narration and args.narration.exists() else ""
    captions = parse_srt(args.srt)
    if not captions:
        captions = fallback_captions(narration, args.duration)
    config = make_config(plan, cast, args.duration, narration, captions, args.audio_asset_id.strip())
    config_json = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    server = server_lua(config_json)
    client = client_lua(config_json)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(make_place(server, client, plan, cast), encoding="utf-8")
    if args.lua_output:
        args.lua_output.parent.mkdir(parents=True, exist_ok=True)
        args.lua_output.write_text(server + "\n-- Camera, caption, and narration playback client is embedded in the place.\n", encoding="utf-8")
    if args.readme:
        args.readme.parent.mkdir(parents=True, exist_ok=True)
        cast_label = ", ".join(member["username"] for member in cast) if cast else "your Roblox player avatar"
        guide = (
            "# Roblox Studio Story Experience\n\n"
            f"**World:** {plan.get('name', 'AI Story World')}  \n"
            f"**Theme:** {plan.get('theme', '')}  \n"
            f"**Duration:** {args.duration} seconds  \n"
            f"**AI-designed props:** {len(plan.get('props', []))}  \n"
            f"**Cast:** {cast_label}\n\n"
            "## Watch the short\n\n"
            "1. Download and unzip `Roblox_Studio_Complete_Package.zip`.\n"
            "2. Play `Roblox_2K_YouTube_Short.mp4` directly. It is rendered automatically by the workflow with the authentic Roblox avatar mesh, world, camera tour, narration, and visible burned-in captions; you do not need to open Roblox Studio.\n"
            "3. The ZIP also includes `AI_Creation_Summary.txt`, `AI_Design_and_Tools_Report.pdf`, narration audio/subtitles, generation prompts, and an optional editable `Roblox_Studio_Experience.rbxlx` project.\n"
            "4. The real Roblox avatar is loaded from the username entered in the workflow. The MP4 is a headless Three.js rendering of the generated world, not a capture from a running Roblox client.\n\n"
            "## Notes\n\n"
            "The workflow renders the MP4 automatically using headless Chromium, Three.js, and FFmpeg; neither Roblox Studio nor Blender needs to be installed or launched. The optional `.rbxlx` project remains editable in Studio. Video validation does not claim a Roblox game-client runtime test.\n"
        )
        args.readme.write_text(guide, encoding="utf-8")
    print(f"Created runnable Roblox Studio place {args.output} with {len(plan.get('props', []))} AI props and {len(cast)} Roblox avatar(s).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--cast", type=Path, required=True)
    parser.add_argument("--duration", type=int, choices=(30, 45, 60), required=True)
    parser.add_argument("--narration", type=Path)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--audio-asset-id", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lua-output", type=Path)
    parser.add_argument("--readme", type=Path)
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
