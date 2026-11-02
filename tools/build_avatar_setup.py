#!/usr/bin/env python3
"""Emit a Roblox Studio script that fetches a public account's current R15 avatar."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_avatar_setup.py ROBLOX_USERNAME OUTPUT.lua")
    username, destination = sys.argv[1], Path(sys.argv[2])
    if username and not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
        raise SystemExit("Roblox username must be 3–20 letters, digits, or underscores.")
    if not username:
        username = "YOUR_ROBLOX_USERNAME"
    quoted_name = '"' + username.replace('"', '\\"') + '"'
    script = f'''-- Loads a public Roblox user's current avatar as a real R15 rig in Studio.
-- Replace USERNAME below if it is still the placeholder.
local Players = game:GetService("Players")
local username = {quoted_name}
if username == "YOUR_ROBLOX_USERNAME" then
    warn("Set username to the Roblox account whose avatar you want to use, then run again.")
    return
end

local userId = Players:GetUserIdFromNameAsync(username)
local description = Players:GetHumanoidDescriptionFromUserIdAsync(userId)
local avatar = Players:CreateHumanoidModelFromDescriptionAsync(description, Enum.HumanoidRigType.R15)
avatar.Name = username .. "_R15"
avatar.Parent = workspace
avatar:PivotTo(CFrame.new(0, 3, 24))
print("Loaded the current R15 avatar for " .. username .. ".")
'''
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(script, encoding="utf-8")
    print(f"Created {destination} for {username}.")


if __name__ == "__main__":
    main()
