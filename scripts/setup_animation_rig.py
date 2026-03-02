"""
Animation Rig Setup — Blender Script Editor
============================================
1. Open System Console: Window > Toggle System Console
2. Edit CONFIGURATION below
3. Click Run Script

Duplicates the entire uf850_twin collection → uf850_animation, renames
_twin → _ani, then builds a standard three-chain FK/IK blend rig:

  Bone Collections
  ─────────────────────────────────────────────
  DEF  joint_1 .. joint_6   hidden   Deform the mesh.
                                      Copy Rotation from FK + IK (blend-driven).
  FK   joint_1_fk .. _6_fk  visible  User rotates for FK control. Blue rings.
  IK   joint_1_ik .. _6_ik  visible  IK solver chain. Rings on J1-J3 for hybrid mode.
       tcp                  visible  Free bone — move this as IK target. Orange cross.

  Custom Properties (on armature)
  ─────────────────────────────────────────────
  ik_fk_blend     (0.0 = FK, 1.0 = IK)
  ik_chain_length (1-6, controls how many joints IK solver affects)

  Three Modes
  ─────────────────────────────────────────────
  Mode A: Full FK
    ik_fk_blend = 0.0
    → Manually rotate all FK bones (blue rings)
    → FK bones have rotation locks + limits applied

  Mode B: Full IK
    ik_fk_blend = 1.0
    ik_chain_length = 6
    → Move TCP anywhere, all 6 joints follow
    → To fix TCP: keyframe it at same position on all frames

  Mode C: Hybrid (FK base + IK tip)
    ik_fk_blend = 1.0
    ik_chain_length = 3
    → Manually rotate J1-J3 IK bones (green rings)
    → Move TCP
    → J4-J6 automatically solve to reach TCP while respecting J1-J3 pose

  Export
  ─────────────────────────────────────────────
  bake_and_export.py reads joint_1..6 (DEF bones) with visual_keying=True.
  Works correctly in any mode — DEF bones always hold the solved rotations.
"""

import bpy
import math
import traceback

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

SOURCE_COLLECTION    = "uf850_twin"       # Source collection to duplicate
OUTPUT_COLLECTION    = "uf850_animation"  # New collection name
SOURCE_SUFFIX        = "_twin"            # Suffix replaced in all object/data names
OUTPUT_SUFFIX        = "_ani"             # New suffix
IK_FK_DEFAULT        = 1.0               # Starting blend: 1 = IK, 0 = FK
IK_CHAIN_DEFAULT     = 6                 # Starting IK chain length (1–6)
                                         # 6 = full IK, 4 = hybrid (J1-J2 manual, J3-J6 IK)
                                         # 3 = hybrid (J1-J3 manual, J4-J6 IK)
WIDGET_SCALE         = 0.16              # Control shape size multiplier

# Robot joint configuration (uf850_twin)
ROTATION_AXES = ['Y', 'Z', '-Z', 'Y', 'Z', 'Y']
JOINT_LIMITS_DEG = [
    (-360,  360),   # J1
    (-132,  132),   # J2
    (-242,  3.5),   # J3
    (-360,  360),   # J4
    (-124,  124),   # J5
    (-360,  360),   # J6
]

# ─────────────────────────────────────────────
# WIDGET HELPERS
# ─────────────────────────────────────────────

WIDGET_COLL = "WIDGETS"


def _widget_collection():
    col = bpy.data.collections.get(WIDGET_COLL)
    if col is None:
        col = bpy.data.collections.new(WIDGET_COLL)
        bpy.context.scene.collection.children.link(col)
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
    verts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        if axis == 'Y':
            verts.append((c, 0.0, s))
        elif axis == 'Z':
            verts.append((c, s, 0.0))
        else:
            verts.append((0.0, c, s))
    return _make_widget(name, verts, [(i, (i + 1) % n) for i in range(n)])


def _cross(name):
    v = [
        (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1),
        (1, 0, 0), (0.8,  0.1, 0), (0.8, -0.1, 0),
        (0, 1, 0), ( 0.1, 0.8, 0), (-0.1, 0.8, 0),
        (0, 0, 1), ( 0.1, 0, 0.8), (-0.1, 0, 0.8),
    ]
    e = [(0,1),(2,3),(4,5),(6,7),(6,8),(9,10),(9,11),(12,13),(12,14)]
    return _make_widget(name, v, e)


# ─────────────────────────────────────────────
# DRIVER HELPER
# ─────────────────────────────────────────────

def _add_driver(obj, data_path, expression, var_name, prop_data_path):
    """SCRIPTED driver: expression uses var_name which reads prop_data_path on obj."""
    if obj.animation_data:
        for fc in list(obj.animation_data.drivers):
            if fc.data_path == data_path:
                obj.animation_data.drivers.remove(fc)
    drv = obj.driver_add(data_path)
    drv.driver.type = 'SCRIPTED'
    drv.driver.expression = expression
    var = drv.driver.variables.new()
    var.name = var_name
    var.type = 'SINGLE_PROP'
    var.targets[0].id = obj
    var.targets[0].data_path = prop_data_path


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run():
    # ── 1. Find source collection ──────────────
    src_coll = bpy.data.collections.get(SOURCE_COLLECTION)
    if src_coll is None:
        print(f"[ERROR] Source collection '{SOURCE_COLLECTION}' not found.")
        print(f"        Collections: {[c.name for c in bpy.data.collections]}")
        return

    if not any(o.type == 'ARMATURE' for o in src_coll.objects):
        print(f"[ERROR] No armature in '{SOURCE_COLLECTION}'.")
        return

    # ── 2. Need VIEW_3D for operators ─────────
    area_3d = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
    if area_3d is None:
        print("[ERROR] No 3D Viewport visible. Open one and run again.")
        return
    region = next((r for r in area_3d.regions if r.type == 'WINDOW'), None)

    # ── 3. Remove old output collection ───────
    old_coll = bpy.data.collections.get(OUTPUT_COLLECTION)
    if old_coll:
        for obj in list(old_coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old_coll)
        print(f"[INFO]  Removed existing '{OUTPUT_COLLECTION}'")

    # ── 4. Create new output collection ───────
    out_coll = bpy.data.collections.new(OUTPUT_COLLECTION)
    bpy.context.scene.collection.children.link(out_coll)
    print(f"[INFO]  Created collection '{OUTPUT_COLLECTION}'")

    # ── 5. Duplicate all objects, rename ──────
    obj_map = {}
    for obj in src_coll.objects:
        new_obj = obj.copy()
        if obj.data is not None:
            new_obj.data = obj.data.copy()
            new_obj.data.name = obj.data.name.replace(SOURCE_SUFFIX, OUTPUT_SUFFIX)
        new_name = obj.name.replace(SOURCE_SUFFIX, OUTPUT_SUFFIX)
        new_obj.name = new_name
        out_coll.objects.link(new_obj)
        obj_map[obj] = new_obj
        print(f"[INFO]    {obj.name!r:30s} → {new_name!r}")

    # ── 6. Fix parent relationships ────────────
    for old_obj, new_obj in obj_map.items():
        if new_obj.parent in obj_map:
            saved_inv = new_obj.matrix_parent_inverse.copy()
            new_obj.parent = obj_map[new_obj.parent]
            new_obj.matrix_parent_inverse = saved_inv

    # ── 7. Fix armature modifiers ──────────────
    for new_obj in out_coll.objects:
        for mod in new_obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object in obj_map:
                mod.object = obj_map[mod.object]

    # ── 8. Locate renamed armature ────────────
    anim_obj = next((o for o in out_coll.objects if o.type == 'ARMATURE'), None)
    if anim_obj is None:
        print("[ERROR] Armature not found after duplication.")
        return
    print(f"[INFO]  Armature: '{anim_obj.name}'")

    expected = [f'joint_{i}' for i in range(1, 7)] + ['tcp']
    missing  = [b for b in expected if b not in anim_obj.pose.bones]
    if missing:
        print(f"[ERROR] Missing bones in '{anim_obj.name}': {missing}")
        return

    # ── 9. Set as active ──────────────────────
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    anim_obj.select_set(True)
    bpy.context.view_layer.objects.active = anim_obj

    # ── 10. Edit Mode — add FK/IK chains + free tcp ──────────────
    with bpy.context.temp_override(area=area_3d, region=region):
        bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = anim_obj.data.edit_bones
        root_parent = edit_bones['joint_1'].parent  # None or base bone

        # Create _fk and _ik copies of every joint bone
        for i in range(1, 7):
            src = edit_bones[f'joint_{i}']
            for suffix in ('_fk', '_ik'):
                b               = edit_bones.new(f'joint_{i}{suffix}')
                b.head          = src.head.copy()
                b.tail          = src.tail.copy()
                b.roll          = src.roll
                b.use_connect   = False
                b.use_deform    = False

        # Parent FK chain (joint_1_fk → root, joint_2_fk → joint_1_fk, …)
        edit_bones['joint_1_fk'].parent = root_parent
        for i in range(2, 7):
            edit_bones[f'joint_{i}_fk'].parent = edit_bones[f'joint_{i-1}_fk']

        # Parent IK chain (same structure)
        edit_bones['joint_1_ik'].parent = root_parent
        for i in range(2, 7):
            edit_bones[f'joint_{i}_ik'].parent = edit_bones[f'joint_{i-1}_ik']

        # TCP is free (no parent) — world space IK target
        tcp_eb = edit_bones['tcp']
        tcp_eb.parent = None
        tcp_eb.use_connect = False
        tcp_eb.use_deform = False

        print("[INFO]  FK chain (joint_1_fk..6_fk) and IK chain (joint_1_ik..6_ik) created")
        print("[INFO]  tcp bone free (no parent) — world space IK target")
        bpy.ops.object.mode_set(mode='OBJECT')

    # ── 11. Pose Mode — constraints ───────────
    with bpy.context.temp_override(area=area_3d, region=region):
        bpy.ops.object.mode_set(mode='POSE')

        pbones = anim_obj.pose.bones

        # Clear all constraints on every bone we'll set up
        all_names = (
            [f'joint_{i}'    for i in range(1, 7)] +
            [f'joint_{i}_fk' for i in range(1, 7)] +
            [f'joint_{i}_ik' for i in range(1, 7)] +
            ['tcp']
        )
        for name in all_names:
            if name in pbones:
                for con in list(pbones[name].constraints):
                    pbones[name].constraints.remove(con)

        # DEF bones: Copy Rotation from FK (1-blend) then from IK (blend)
        for i in range(1, 7):
            pb = pbones[f'joint_{i}']

            fk_con              = pb.constraints.new('COPY_ROTATION')
            fk_con.name         = 'Copy FK'
            fk_con.target       = anim_obj
            fk_con.subtarget    = f'joint_{i}_fk'
            fk_con.target_space = 'LOCAL'
            fk_con.owner_space  = 'LOCAL'
            fk_con.influence    = 1.0 - IK_FK_DEFAULT

            ik_con              = pb.constraints.new('COPY_ROTATION')
            ik_con.name         = 'Copy IK'
            ik_con.target       = anim_obj
            ik_con.subtarget    = f'joint_{i}_ik'
            ik_con.target_space = 'LOCAL'
            ik_con.owner_space  = 'LOCAL'
            ik_con.influence    = IK_FK_DEFAULT

        # IK solver on joint_6_ik targeting the free tcp bone
        ik_main              = pbones['joint_6_ik'].constraints.new('IK')
        ik_main.name         = 'IK'
        ik_main.target       = anim_obj
        ik_main.subtarget    = 'tcp'
        ik_main.chain_count  = IK_CHAIN_DEFAULT
        ik_main.use_rotation = True

        print("[INFO]  Copy Rotation (FK + IK) added to DEF bones joint_1..6")
        print("[INFO]  IK solver on joint_6_ik → tcp bone (same armature)")

        # ── Apply IK locks and joint limits ──────
        # For each joint, lock IK on all axes EXCEPT the rotation axis
        # and set joint limits (converted to radians with sign handling)

        for i in range(1, 7):
            axis_spec = ROTATION_AXES[i - 1]
            limits_deg = JOINT_LIMITS_DEG[i - 1]

            # Parse axis: '-Z' → sign=-1, axis='Z'
            if axis_spec.startswith('-'):
                sign = -1
                axis_char = axis_spec[1:]
            else:
                sign = 1
                axis_char = axis_spec

            # Convert limits to radians, flip if negative axis
            min_deg, max_deg = limits_deg
            if sign == -1:
                min_rad = math.radians(-max_deg)  # Flip
                max_rad = math.radians(-min_deg)
            else:
                min_rad = math.radians(min_deg)
                max_rad = math.radians(max_deg)

            # Apply to all three bone types: DEF, FK, IK
            for suffix in ('', '_fk', '_ik'):
                pb = pbones[f'joint_{i}{suffix}']

                # IK locks: lock all axes except the rotation axis
                pb.lock_ik_x = (axis_char != 'X')
                pb.lock_ik_y = (axis_char != 'Y')
                pb.lock_ik_z = (axis_char != 'Z')

                # Joint limits on the rotation axis only
                if axis_char == 'X':
                    pb.use_ik_limit_x = True
                    pb.ik_min_x = min_rad
                    pb.ik_max_x = max_rad
                elif axis_char == 'Y':
                    pb.use_ik_limit_y = True
                    pb.ik_min_y = min_rad
                    pb.ik_max_y = max_rad
                else:  # 'Z'
                    pb.use_ik_limit_z = True
                    pb.ik_min_z = min_rad
                    pb.ik_max_z = max_rad

        print("[INFO]  IK locks and joint limits applied to all bones (DEF, FK, IK)")

        # ── FK bone constraints (lock location, lock rotation, limit rotation) ──────
        for i in range(1, 7):
            axis_spec = ROTATION_AXES[i - 1]
            limits_deg = JOINT_LIMITS_DEG[i - 1]

            # Parse axis
            if axis_spec.startswith('-'):
                sign = -1
                axis_char = axis_spec[1:]
            else:
                sign = 1
                axis_char = axis_spec

            # Convert limits
            min_deg, max_deg = limits_deg
            if sign == -1:
                min_rad = math.radians(-max_deg)
                max_rad = math.radians(-min_deg)
            else:
                min_rad = math.radians(min_deg)
                max_rad = math.radians(max_deg)

            pb_fk = pbones[f'joint_{i}_fk']

            # Lock location (FK bones can't translate)
            pb_fk.lock_location = (True, True, True)

            # Lock rotation on non-active axes
            pb_fk.lock_rotation = (
                axis_char != 'X',  # Lock X if not rotation axis
                axis_char != 'Y',  # Lock Y if not rotation axis
                axis_char != 'Z',  # Lock Z if not rotation axis
            )

            # Add Limit Rotation constraint on active axis
            limit_con = pb_fk.constraints.new('LIMIT_ROTATION')
            limit_con.name = 'Limit Rotation'
            limit_con.use_transform_limit = True
            limit_con.owner_space = 'LOCAL'

            if axis_char == 'X':
                limit_con.use_limit_x = True
                limit_con.min_x = min_rad
                limit_con.max_x = max_rad
            elif axis_char == 'Y':
                limit_con.use_limit_y = True
                limit_con.min_y = min_rad
                limit_con.max_y = max_rad
            else:  # 'Z'
                limit_con.use_limit_z = True
                limit_con.min_z = min_rad
                limit_con.max_z = max_rad

        print("[INFO]  FK bone constraints: location locked, rotation locked + limited")

        bpy.ops.object.mode_set(mode='OBJECT')

    # ── 12. Custom properties ─────────────────
    # Mode selector: 0=FK, 1=IK, 2=Hybrid
    # Determines default based on IK_CHAIN_DEFAULT
    default_mode = 2 if IK_CHAIN_DEFAULT in (3, 4) else (1 if IK_FK_DEFAULT == 1.0 else 0)

    anim_obj["mode"] = default_mode
    anim_obj.id_properties_ui("mode").update(
        min=0, max=2,
        soft_min=0, soft_max=2,
        description="0 = Mode A (Full FK)  |  1 = Mode B (Full IK)  |  2 = Mode C (Hybrid)",
    )
    print(f"[INFO]  Custom property: mode = {default_mode} ({'FK' if default_mode==0 else 'IK' if default_mode==1 else 'Hybrid'})")

    # Internal blend property (driven by mode)
    anim_obj["ik_fk_blend"] = 1.0 if default_mode >= 1 else 0.0
    anim_obj.id_properties_ui("ik_fk_blend").update(
        min=0.0, max=1.0,
        soft_min=0.0, soft_max=1.0,
        description="Auto-set by mode property (don't change manually)",
    )

    # ── 13. Drivers ───────────────────────────
    # Driver: mode → ik_fk_blend (mode 0 = 0.0, mode 1/2 = 1.0)
    blend_path = '["ik_fk_blend"]'
    if anim_obj.animation_data:
        for fc in list(anim_obj.animation_data.drivers):
            if fc.data_path == blend_path:
                anim_obj.animation_data.drivers.remove(fc)

    drv = anim_obj.driver_add(blend_path)
    drv.driver.type = 'SCRIPTED'
    drv.driver.expression = '1.0 if mode >= 1 else 0.0'
    var = drv.driver.variables.new()
    var.name = 'mode'
    var.type = 'SINGLE_PROP'
    var.targets[0].id = anim_obj
    var.targets[0].data_path = '["mode"]'

    print("[INFO]  Driver: mode → ik_fk_blend (0=FK uses 0.0, 1/2=IK uses 1.0)")

    # Driver: ik_fk_blend → constraint influences (same as before)
    for i in range(1, 7):
        fk_path = f'pose.bones["joint_{i}"].constraints["Copy FK"].influence'
        ik_path = f'pose.bones["joint_{i}"].constraints["Copy IK"].influence'
        _add_driver(anim_obj, fk_path, '1 - blend', 'blend', '["ik_fk_blend"]')
        _add_driver(anim_obj, ik_path, 'blend',     'blend', '["ik_fk_blend"]')

    print("[INFO]  Drivers: ik_fk_blend → all joint constraints")

    # Set IK chain_count to default (NOT driven - Blender doesn't allow it)
    ik_main = pbones['joint_6_ik'].constraints.get('IK')
    if ik_main:
        ik_main.chain_count = IK_CHAIN_DEFAULT
        print(f"[INFO]  IK chain_count set to {IK_CHAIN_DEFAULT}")
        print(f"[NOTE]  chain_count is NOT animatable - must be changed manually in Pose Mode")

    # ── 14. Bone Collections (Blender 4.0+ API) ──────────────────
    arm_data = anim_obj.data

    for name in ('DEF', 'FK', 'IK'):
        existing = arm_data.collections.get(name)
        if existing:
            arm_data.collections.remove(existing)

    col_def = arm_data.collections.new('DEF')
    col_fk  = arm_data.collections.new('FK')
    col_ik  = arm_data.collections.new('IK')

    # Set visibility based on mode
    col_def.is_visible = False    # DEF bones always hidden (deform only)
    col_fk.is_visible = (default_mode != 2)  # FK hidden in hybrid mode (mode 2)
    col_ik.is_visible = True      # IK always visible

    for i in range(1, 7):
        col_def.assign(arm_data.bones[f'joint_{i}'])
        col_fk.assign(arm_data.bones[f'joint_{i}_fk'])
        col_ik.assign(arm_data.bones[f'joint_{i}_ik'])
    col_ik.assign(arm_data.bones['tcp'])

    fk_vis = "visible" if col_fk.is_visible else "hidden"
    print(f"[INFO]  Bone collections: DEF (hidden), FK ({fk_vis}), IK (visible)")

    # ── 15. Widgets + Colors ──────────────────
    ring_axes = ['Y', 'Z', 'Z', 'Y', 'Z', 'Y']
    pbones    = anim_obj.pose.bones
    s         = WIDGET_SCALE

    # FK bones: blue rings
    for i in range(1, 7):
        pb                            = pbones[f'joint_{i}_fk']
        pb.custom_shape               = _circle(f'WGT_joint_{i}_fk', axis=ring_axes[i-1])
        pb.use_custom_shape_bone_size = False
        pb.custom_shape_scale_xyz     = (s, s, s)
        pb.color.palette              = 'THEME04'   # Blue

    # IK bones J1-J3: green rings (for hybrid mode manual rotation)
    for i in range(1, 4):
        pb                            = pbones[f'joint_{i}_ik']
        pb.custom_shape               = _circle(f'WGT_joint_{i}_ik', axis=ring_axes[i-1])
        pb.use_custom_shape_bone_size = False
        pb.custom_shape_scale_xyz     = (s, s, s)
        pb.color.palette              = 'THEME03'   # Green

    # IK bones J4-J6: no widget (controlled by IK solver)
    for i in range(4, 7):
        pbones[f'joint_{i}_ik'].custom_shape = None

    # tcp: orange cross
    tcp_pb                            = pbones['tcp']
    tcp_pb.custom_shape               = _cross('WGT_tcp')
    tcp_pb.use_custom_shape_bone_size = False
    tcp_pb.custom_shape_scale_xyz     = (s * 1.5, s * 1.5, s * 1.5)
    tcp_pb.color.palette              = 'THEME09'   # Orange

    # DEF bones: no widget (hidden)
    for i in range(1, 7):
        pbones[f'joint_{i}'].custom_shape = None

    print("[INFO]  Widgets: FK rings (blue), IK J1-J3 rings (green), tcp cross (orange)")

    # ── Done ──────────────────────────────────
    print()
    print(f"[DONE]  Collection '{OUTPUT_COLLECTION}' ready for animation")
    print(f"        Armature: '{anim_obj.name}'")
    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  HOW TO USE")
    print("  ═══════════════════════════════════════════════════════════")
    print(f"  Select '{anim_obj.name}' → Object Properties → Custom Properties")
    print()
    print("  MAIN CONTROL:")
    print("    mode = 0, 1, or 2  (switches between three operating modes)")
    print()
    print("      0 = Mode A (Full FK)")
    print("      1 = Mode B (Full IK)")
    print("      2 = Mode C (Hybrid)")
    print()
    print(f"  Current mode: {default_mode} ({'A - Full FK' if default_mode==0 else 'B - Full IK' if default_mode==1 else 'C - Hybrid'})")
    print()
    print("  The mode property automatically sets:")
    print("    - ik_fk_blend (FK/IK blend)")
    print("    - FK bone collection visibility (hidden in hybrid mode)")
    print()
    print("  MANUAL STEP (for modes B & C):")
    print("    Pose Mode → select joint_6_ik → Bone Constraints → IK → Chain Length")
    print("      Mode B: set to 6 (all joints solve)")
    print("      Mode C: set to 4 (J1-J2 manual, J3-J6 solve) or 3 (J1-J3 manual, J4-J6 solve)")
    print(f"    Current: {IK_CHAIN_DEFAULT}")
    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  MODE A: Full FK (Manual Posing)")
    print("  ═══════════════════════════════════════════════════════════")
    print("    1. Set mode = 0")
    print("    2. Pose Mode → rotate blue FK bones (joint_N_fk)")
    print("    3. FK bones have rotation locks + limits")
    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  MODE B: Full IK (Animated or Fixed TCP)")
    print("  ═══════════════════════════════════════════════════════════")
    print("    1. Set mode = 1")
    print("    2. Pose Mode → select joint_6_ik → Bone Constraints → IK → Chain Length = 6")
    print("    3. Grab/move orange tcp bone")
    print("    4. All 6 joints automatically solve")
    print()
    print("    FIXED TCP (robot head fixed):")
    print("      - Position TCP at desired location")
    print("      - Keyframe TCP position on frame 0 and last frame (same position)")
    print("      - TCP stays static, joints move within IK redundancy")
    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  MODE C: Hybrid (Manual Base + IK Tip)")
    print("  ═══════════════════════════════════════════════════════════")
    print("    1. Set mode = 2  (auto-hides FK bones, sets blend=1.0)")
    print("    2. Pose Mode → select joint_6_ik → Bone Constraints → IK → Chain Length = 4")
    print("    3. Rotate green IK bones J1-J2 (elbow preference)")
    print("    4. Move orange TCP")
    print("    5. J3-J6 automatically solve to reach TCP")
    print()
    print("    OPTION: Chain Length = 3 instead")
    print("      → Rotate J1-J3 manually, J4-J6 solve")
    print()
    print("    → All rotation from IK chain (FK bones hidden)")
    print("    → Control elbow preference by rotating green IK bones")
    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  JOINT LIMITS & IK LOCKS")
    print("  ═══════════════════════════════════════════════════════════")
    print("    - IK locks: only rotate on configured axis per joint")
    print("    - Joint limits: robot spec applied (uf850_twin)")
    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  EXPORT")
    print("  ═══════════════════════════════════════════════════════════")
    print(f"    Set bake_and_export.py  ARMATURE_NAME = '{anim_obj.name}'")
    print("    All modes export correctly — DEF bones hold final solved rotations")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

try:
    run()
except Exception:
    print()
    print("[EXCEPTION]")
    print(traceback.format_exc())
