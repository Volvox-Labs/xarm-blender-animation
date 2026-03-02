"""
FK/IK Blend Rig Setup — Blender Script Editor
==============================================
1. Open System Console: Window > Toggle System Console
2. Run animaquinauf's "Set Simulation" button FIRST
3. Edit CONFIGURATION below
4. Click Run Script

What this adds to the sim armature:
  - 'ik_fk_blend' custom property  (0.0 = full FK, 1.0 = full IK)
  - Driver on the IK constraint influence
  - Procedural control shapes (rings for FK joints, cross for TCP)
  - Bone color coding  (blue = FK joints, orange = TCP/IK)

Usage after setup:
  - Select armature → Object Properties → Custom Properties
  - 'ik_fk_blend' = 1.0  →  IK mode: move TCP target object
  - 'ik_fk_blend' = 0.0  →  FK mode: rotate joint bones directly
  - Keyframe 'ik_fk_blend' to switch modes during animation
"""

import bpy
import math
import traceback

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

ARMATURE_NAME   = "uf850_animation"   # Armature name after "Set Simulation"
IK_FK_DEFAULT   = 1.0           # Starting value: 1 = IK, 0 = FK
WIDGET_SCALE    = 1.0           # Control shape scale multiplier (adjust to taste)

# ─────────────────────────────────────────────
# WIDGET HELPERS
# ─────────────────────────────────────────────

WIDGET_COLL = "WIDGETS"


def _widget_collection():
    col = bpy.data.collections.get(WIDGET_COLL)
    if col is None:
        col = bpy.data.collections.new(WIDGET_COLL)
        bpy.context.scene.collection.children.link(col)
    # Hide the widget collection — widgets are display-only
    lc = bpy.context.view_layer.layer_collection.children.get(WIDGET_COLL)
    if lc:
        lc.hide_viewport = True
    return col


def _make_widget(name, verts, edges):
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    _widget_collection().objects.link(obj)
    return obj


def _circle(name, n=32, axis='Z'):
    """Ring widget. axis sets the plane of rotation to visualize."""
    verts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        if axis == 'Y':
            verts.append((c, 0.0, s))
        elif axis == 'Z':
            verts.append((c, s, 0.0))
        else:   # X
            verts.append((0.0, c, s))
    edges = [(i, (i + 1) % n) for i in range(n)]
    return _make_widget(name, verts, edges)


def _cross(name):
    """3-axis cross with arrow tips for the TCP IK target."""
    v = [
        # axes
        (-1, 0, 0), (1, 0, 0),
        (0, -1, 0), (0, 1, 0),
        (0, 0, -1), (0, 0, 1),
        # +X arrowhead
        (1, 0, 0), (0.8,  0.1, 0), (0.8, -0.1, 0),
        # +Y arrowhead
        (0, 1, 0), ( 0.1, 0.8, 0), (-0.1, 0.8, 0),
        # +Z arrowhead
        (0, 0, 1), ( 0.1, 0, 0.8), (-0.1, 0, 0.8),
    ]
    e = [
        (0, 1), (2, 3), (4, 5),
        (6, 7), (6, 8),
        (9, 10), (9, 11),
        (12, 13), (12, 14),
    ]
    return _make_widget(name, v, e)


def _sphere(name, n=16):
    """Three orthogonal rings — good for a ball/pivot widget."""
    verts, edges = [], []
    for plane in ('XY', 'XZ', 'YZ'):
        base = len(verts)
        for i in range(n):
            a = 2 * math.pi * i / n
            c, s = math.cos(a), math.sin(a)
            if plane == 'XY':
                verts.append((c, s, 0))
            elif plane == 'XZ':
                verts.append((c, 0, s))
            else:
                verts.append((0, c, s))
        edges += [(base + i, base + (i + 1) % n) for i in range(n)]
    return _make_widget(name, verts, edges)


# ─────────────────────────────────────────────
# MAIN SETUP
# ─────────────────────────────────────────────

def run():
    arm_obj = bpy.data.objects.get(ARMATURE_NAME)
    if arm_obj is None or arm_obj.type != 'ARMATURE':
        print(f"[ERROR] Armature '{ARMATURE_NAME}' not found.")
        print(f"        Armatures in scene: {[o.name for o in bpy.data.objects if o.type == 'ARMATURE']}")
        return

    pbones = arm_obj.pose.bones
    expected = [f'joint_{i}' for i in range(1, 7)] + ['tcp']
    missing = [b for b in expected if b not in pbones]
    if missing:
        print(f"[ERROR] Missing bones: {missing}")
        print("        Run animaquinauf 'Set Simulation' first, then re-run this script.")
        return

    # ── 1. Custom property: ik_fk_blend ──────
    arm_obj["ik_fk_blend"] = float(IK_FK_DEFAULT)
    arm_obj.id_properties_ui("ik_fk_blend").update(
        min=0.0, max=1.0,
        soft_min=0.0, soft_max=1.0,
        description="0 = FK (rotate joints)  |  1 = IK (move TCP target)",
    )
    print(f"[INFO]  'ik_fk_blend' property added  (default {IK_FK_DEFAULT})")

    # ── 2. Find IK constraint on joint_6 ─────
    ik_con = next((c for c in pbones['joint_6'].constraints if c.type == 'IK'), None)
    if ik_con is None:
        print("[ERROR] No IK constraint on joint_6.")
        print("        Run animaquinauf 'Set Simulation' first.")
        return

    # ── 3. Driver: ik_fk_blend → IK influence ─
    # Remove any pre-existing driver on this path
    con_path = f'pose.bones["joint_6"].constraints["{ik_con.name}"].influence'
    if arm_obj.animation_data:
        for fc in list(arm_obj.animation_data.drivers):
            if fc.data_path == con_path:
                arm_obj.animation_data.drivers.remove(fc)

    drv = arm_obj.driver_add(con_path)
    drv.driver.type = 'AVERAGE'
    var = drv.driver.variables.new()
    var.name = 'blend'
    var.type = 'SINGLE_PROP'
    var.targets[0].id = arm_obj
    var.targets[0].data_path = '["ik_fk_blend"]'
    print(f"[INFO]  Driver: ik_fk_blend → '{ik_con.name}'.influence")

    # ── 4. Build widgets ──────────────────────
    # Rotation axes for joint_1..6: Y Z -Z Y Z Y  (strip sign, use for ring plane)
    axes = ['Y', 'Z', 'Z', 'Y', 'Z', 'Y']
    joint_wgts = {
        f'joint_{i+1}': _circle(f'WGT_joint_{i+1}', axis=axes[i])
        for i in range(6)
    }
    tcp_wgt = _cross("WGT_tcp")
    print(f"[INFO]  Widgets created in '{WIDGET_COLL}' collection (hidden)")

    # ── 5. Assign custom shapes ───────────────
    s = WIDGET_SCALE
    for i in range(1, 7):
        pb = pbones[f'joint_{i}']
        pb.custom_shape               = joint_wgts[f'joint_{i}']
        pb.use_custom_shape_bone_size = True   # scale with bone length
        pb.custom_shape_scale_xyz     = (s, s, s)

    tcp_pb = pbones['tcp']
    tcp_pb.custom_shape               = tcp_wgt
    tcp_pb.use_custom_shape_bone_size = True
    tcp_pb.custom_shape_scale_xyz     = (s * 1.5, s * 1.5, s * 1.5)

    print("[INFO]  Custom shapes assigned to all bones")

    # ── 6. Bone colors ────────────────────────
    # Blue  (THEME04) = FK joint controls
    # Orange (THEME09) = IK / TCP control
    for i in range(1, 7):
        pbones[f'joint_{i}'].color.palette = 'THEME04'
    pbones['tcp'].color.palette = 'THEME09'
    print("[INFO]  Colors: blue = FK joints, orange = TCP")

    # ── Done ─────────────────────────────────
    print()
    print(f"[DONE]  '{ARMATURE_NAME}' FK/IK blend rig ready")
    print()
    print("  HOW TO USE")
    print(f"  Select '{ARMATURE_NAME}' → Object Properties → Custom Properties")
    print("  ik_fk_blend = 1.0  →  IK mode  (grab orange TCP target, arm follows)")
    print("  ik_fk_blend = 0.0  →  FK mode  (rotate blue joint bones directly)")
    print("  Keyframe 'ik_fk_blend' to switch modes during animation")
    print()
    print("  EXPORT")
    print("  Both modes export correctly — bake_and_export.py reads the solved")
    print("  bone rotations regardless of whether IK or FK drove them.")
    print()
    print("  TIP: To snap FK to IK pose when switching:")
    print("  Pose Mode → select all → Pose → Clear Transform (individual)")
    print("  then key-insert the joint bones at the current IK position.")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

try:
    run()
except Exception:
    print()
    print("[EXCEPTION]")
    print(traceback.format_exc())
