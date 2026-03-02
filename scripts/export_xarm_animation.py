"""
xArm Animation Export — Blender Script Editor
==============================================
1. Open the System Console first:  Window > Toggle System Console
2. Edit the CONFIGURATION block below
3. Click Run Script  — output appears in the System Console
"""

import bpy
import csv
import math
import os
import traceback
from typing import List, Tuple

# ─────────────────────────────────────────────
# CONFIGURATION — edit these before running
# ─────────────────────────────────────────────

ARMATURE_NAME   = "uf850_twin"          # Name of your robot armature in the scene
OUTPUT_PATH     = r"C:\Users\vvox\Documents\GitHub\COBOT-IK-CONTROL\animation.csv"
ROBOT_TYPE      = "uf850_twin"          # "uf850_twin" or "ufxarm6_twin"
FPS             = 30.0                  # 30 = cued playback, 250 = servo mode
MAX_SPEED_PCT   = 50.0                  # Max speed cap (0–100). 50 = safe default
START_FRAME     = None                  # None = use scene start
END_FRAME       = None                  # None = use scene end
ACTION_NAME     = None                  # None = use active action. Set to "ActionName" to pick a specific one.
                                        # Run:  print([a.name for a in bpy.data.actions])  to list all actions

# ─────────────────────────────────────────────
# ROBOT CONFIGS
# ─────────────────────────────────────────────

ROBOT_CONFIGS = {
    "uf850_twin": {
        "bone_names": ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"],
        "rotation_axes": ["Y", "Z", "-Z", "Y", "Z", "Y"],
        "joint_limits_deg": [
            (-360,  360),   # J1
            (-132,  132),   # J2
            (-242,  3.5),   # J3
            (-360,  360),   # J4
            (-124,  124),   # J5
            (-360,  360),   # J6
        ],
        "max_velocity_deg_s": 180.0,
    },
    "ufxarm6_twin": {
        "bone_names": ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"],
        "rotation_axes": ["Y", "-Z", "-Z", "Y", "-Z", "Y"],
        "joint_limits_deg": [
            (-360,  360),
            (-132,  132),
            (-242,  3.5),
            (-360,  360),
            (-124,  124),
            (-360,  360),
        ],
        "max_velocity_deg_s": 180.0,
    },
}

# ─────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────

def get_joint_angles(armature_obj, bone_names: List[str], rotation_axes: List[str], frame: int) -> List[float]:
    bpy.context.scene.frame_set(frame)
    angles = []
    for bone_name, axis in zip(bone_names, rotation_axes):
        bone = armature_obj.pose.bones[bone_name]
        bone.rotation_mode = "XYZ"
        if axis.startswith("-"):
            sign, axis_char = -1, axis[1:]
        else:
            sign, axis_char = 1, axis
        axis_idx = {"X": 0, "Y": 1, "Z": 2}[axis_char]
        angles.append(math.degrees(bone.rotation_euler[axis_idx]) * sign)
    return angles


def check_limits(angles: List[float], limits: List[Tuple], frame: int) -> List[str]:
    violations = []
    for j, (angle, (lo, hi)) in enumerate(zip(angles, limits)):
        if angle < lo or angle > hi:
            violations.append(f"  Frame {frame:4d}  J{j+1}: {angle:8.2f} deg  (limit [{lo:.1f}, {hi:.1f}])")
    return violations


def calc_speed(prev: List[float], curr: List[float], frame_time: float, max_vel: float, cap: float) -> Tuple[float, List[float]]:
    vels = [abs(c - p) / frame_time for p, c in zip(prev, curr)]
    pct  = min((max(vels) / max_vel) * 100.0, cap)
    return pct, vels


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run():
    cfg = ROBOT_CONFIGS.get(ROBOT_TYPE)
    if cfg is None:
        print(f"[ERROR] Unknown ROBOT_TYPE: '{ROBOT_TYPE}'")
        print(f"        Choose from: {list(ROBOT_CONFIGS)}")
        return

    start = START_FRAME if START_FRAME is not None else bpy.context.scene.frame_start
    end   = END_FRAME   if END_FRAME   is not None else bpy.context.scene.frame_end

    arm_obj = bpy.data.objects.get(ARMATURE_NAME)
    if arm_obj is None or arm_obj.type != "ARMATURE":
        print(f"[ERROR] Armature '{ARMATURE_NAME}' not found.")
        print(f"        Objects in scene: {[o.name for o in bpy.data.objects]}")
        return

    missing = [b for b in cfg["bone_names"] if b not in arm_obj.pose.bones]
    if missing:
        print(f"[ERROR] Missing bones: {missing}")
        print(f"        Bones in armature: {[b.name for b in arm_obj.pose.bones]}")
        return

    # ── Action selection ─────────────────────
    original_action = arm_obj.animation_data.action if arm_obj.animation_data else None
    if ACTION_NAME is not None:
        action = bpy.data.actions.get(ACTION_NAME)
        if action is None:
            print(f"[ERROR] Action '{ACTION_NAME}' not found.")
            print(f"        Available actions: {[a.name for a in bpy.data.actions]}")
            return
        arm_obj.animation_data.action = action
        print(f"[INFO]  Switched to action: {ACTION_NAME}")
    else:
        active = original_action.name if original_action else "none"
        print(f"[INFO]  Using active action: {active}")

    out_dir = os.path.dirname(OUTPUT_PATH)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)

    bone_names = cfg["bone_names"]
    axes       = cfg["rotation_axes"]
    limits     = cfg["joint_limits_deg"]
    max_vel    = cfg["max_velocity_deg_s"]
    frame_time = 1.0 / FPS

    rows             = []
    limit_violations = []
    speed_warnings   = []
    max_vels         = [0.0] * 6
    prev_angles      = None

    print(f"[EXPORT]  armature : {ARMATURE_NAME}")
    print(f"          robot    : {ROBOT_TYPE}")
    print(f"          frames   : {start} - {end}  ({end - start + 1} total)")
    print(f"          fps      : {FPS}")
    print(f"          output   : {OUTPUT_PATH}")
    print()

    for frame in range(start, end + 1):
        angles = get_joint_angles(arm_obj, bone_names, axes, frame)
        time_s = (frame - start) / FPS

        limit_violations += check_limits(angles, limits, frame)

        if prev_angles is not None:
            speed, vels = calc_speed(prev_angles, angles, frame_time, max_vel, MAX_SPEED_PCT)
            for j, v in enumerate(vels):
                max_vels[j] = max(max_vels[j], v)
                if v > max_vel * 0.8:
                    speed_warnings.append(
                        f"  Frame {frame:4d}  J{j+1}: {v:.1f} deg/s  (>{max_vel*0.8:.0f} threshold)"
                    )
        else:
            speed = MAX_SPEED_PCT

        rows.append({
            "frame":     frame,
            "time_s":    f"{time_s:.4f}",
            "j1_deg":    f"{angles[0]:.6f}",
            "j2_deg":    f"{angles[1]:.6f}",
            "j3_deg":    f"{angles[2]:.6f}",
            "j4_deg":    f"{angles[3]:.6f}",
            "j5_deg":    f"{angles[4]:.6f}",
            "j6_deg":    f"{angles[5]:.6f}",
            "speed_pct": f"{speed:.2f}",
        })
        prev_angles = angles

    # Write CSV
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # ── Report ───────────────────────────────
    print(f"[DONE]  {len(rows)} frames written")
    print()
    print("Max joint velocities (deg/s):")
    for j, v in enumerate(max_vels):
        bar  = "#" * int(v / max_vel * 30)
        warn = "  <-- WARNING" if v > max_vel * 0.8 else ""
        print(f"  J{j+1}  {v:7.1f}  {bar}{warn}")

    print()
    if limit_violations:
        print(f"LIMIT VIOLATIONS ({len(limit_violations)}):")
        for msg in limit_violations[:20]:
            print(msg)
        if len(limit_violations) > 20:
            print(f"  ... and {len(limit_violations) - 20} more")
    else:
        print("No joint limit violations.")

    print()
    if speed_warnings:
        print(f"SPEED WARNINGS ({len(speed_warnings)}):")
        for msg in speed_warnings[:20]:
            print(msg)
        if len(speed_warnings) > 20:
            print(f"  ... and {len(speed_warnings) - 20} more")
    else:
        print("No speed warnings.")

    # Restore original action if we switched
    if ACTION_NAME is not None and arm_obj.animation_data:
        arm_obj.animation_data.action = original_action


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

try:
    run()
except Exception:
    print()
    print("[EXCEPTION]")
    print(traceback.format_exc())
