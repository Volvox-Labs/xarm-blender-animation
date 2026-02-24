"""
Setup Rig Operator

Creates FK/IK animation rig from source twin collection with dynamic mode switching.
Converts blender/scripts/setup_animation_rig.py into operator with UI parameters.
"""

import bpy
import math


# ─────────────────────────────────────────────
# POLL FUNCTIONS
# ─────────────────────────────────────────────

def xarm_rig_poll(self, obj):
    """Filter for armatures with xarm_robot_type property (created by Setup Rig)."""
    return obj.type == 'ARMATURE' and obj.get("xarm_robot_type") is not None


# ─────────────────────────────────────────────
# WIDGET HELPERS
# ─────────────────────────────────────────────

WIDGET_COLL = "WIDGETS"


def _widget_collection():
    """Get or create widget collection (hidden from viewport)."""
    col = bpy.data.collections.get(WIDGET_COLL)
    if col is None:
        col = bpy.data.collections.new(WIDGET_COLL)
        bpy.context.scene.collection.children.link(col)
    lc = bpy.context.view_layer.layer_collection.children.get(WIDGET_COLL)
    if lc:
        lc.hide_viewport = True
    return col


def _make_widget(name, verts, edges):
    """Create or replace widget mesh object."""
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    obj = bpy.data.objects.new(name, mesh)
    _widget_collection().objects.link(obj)
    return obj


def _circle(name, n=32, axis='Z'):
    """Create ring widget (visualizes rotation axis)."""
    verts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        if axis == 'Y':
            verts.append((c, 0.0, s))
        elif axis == 'Z':
            verts.append((c, s, 0.0))
        else:  # X
            verts.append((0.0, c, s))
    return _make_widget(name, verts, [(i, (i + 1) % n) for i in range(n)])


def _cross(name):
    """Create 3-axis cross widget with arrow tips (for TCP IK target)."""
    v = [
        # Axes
        (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1),
        # +X arrowhead
        (1, 0, 0), (0.8,  0.1, 0), (0.8, -0.1, 0),
        # +Y arrowhead
        (0, 1, 0), ( 0.1, 0.8, 0), (-0.1, 0.8, 0),
        # +Z arrowhead
        (0, 0, 1), ( 0.1, 0, 0.8), (-0.1, 0, 0.8),
    ]
    e = [(0,1), (2,3), (4,5), (6,7), (6,8), (9,10), (9,11), (12,13), (12,14)]
    return _make_widget(name, v, e)


# ─────────────────────────────────────────────
# DRIVER HELPER
# ─────────────────────────────────────────────

def _add_driver(obj, data_path, expression, var_name, prop_data_path):
    """
    Add SCRIPTED driver: expression uses var_name which reads prop_data_path on obj.

    Args:
        obj: Object to add driver to
        data_path: Property path to drive (e.g., 'pose.bones["joint_1"].constraints["Copy FK"].influence')
        expression: Python expression (e.g., '1 - blend')
        var_name: Variable name used in expression (e.g., 'blend')
        prop_data_path: Property path to read (e.g., '["ik_fk_blend"]')
    """
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
# MODE UPDATE CALLBACK (Critical for dynamic switching)
# ─────────────────────────────────────────────

def xarm_mode_update_callback(armature_obj, context):
    """
    Called when xarm_mode property changes on armature object.

    Updates:
    1. FK collection visibility (hidden in hybrid mode)
    2. IK chain_count (0 for FK, 6 for full IK, 3 for hybrid)
    3. Internal custom property for drivers
    4. Viewport redraw

    Args:
        armature_obj: The armature object (self in property context)
        context: Blender context
    """
    # Safety check - ensure EnumProperty exists
    if not hasattr(armature_obj, 'xarm_mode'):
        return

    # Read from EnumProperty (string '0', '1', '2')
    mode = int(armature_obj.xarm_mode)

    # Sync to custom property for drivers (they need numeric values)
    armature_obj["xarm_mode"] = mode

    # 1. Update bone collection visibility
    try:
        fk_collection = armature_obj.data.collections.get("FK")
        ik_collection = armature_obj.data.collections.get("IK")

        if fk_collection and ik_collection:
            # Mode 0 (FK): FK visible, IK hidden
            # Mode 1 (IK): FK hidden, IK visible
            # Mode 2 (Hybrid): FK hidden, IK visible
            if mode == 0:
                fk_collection.is_visible = True
                ik_collection.is_visible = False
            else:  # mode 1 or 2
                fk_collection.is_visible = False
                ik_collection.is_visible = True

            print(f"[xArm] FK visibility: {fk_collection.is_visible}, IK visibility: {ik_collection.is_visible}")
    except Exception as e:
        print(f"[xArm] Failed to update bone visibility: {e}")

    # 2. Update IK chain_count
    try:
        joint_6_ik = armature_obj.pose.bones.get("joint_6_ik")
        if joint_6_ik:
            ik_constraint = joint_6_ik.constraints.get("IK")
            if ik_constraint:
                # Mode 0 (FK): chain_count=0 (disable IK)
                # Mode 1 (IK): chain_count=6 (full IK on all 6 joints)
                # Mode 2 (Hybrid): chain_count=4 (J1-J2 manual, J3-J6 solve)
                chain_map = {0: 0, 1: 6, 2: 4}
                ik_constraint.chain_count = chain_map.get(mode, 6)
                print(f"[xArm] IK chain_count: {ik_constraint.chain_count}")
    except Exception as e:
        print(f"[xArm] Failed to update IK chain_count: {e}")

    # 3. Force viewport redraw
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def xarm_ik_rotation_update_callback(armature_obj, context):
    """
    Called when xarm_ik_track_rotation property changes.

    Updates IK constraint use_rotation setting (whether IK tracks TCP rotation or just position).

    Args:
        armature_obj: The armature object
        context: Blender context
    """
    if not hasattr(armature_obj, 'xarm_ik_track_rotation'):
        return

    try:
        joint_6_ik = armature_obj.pose.bones.get("joint_6_ik")
        if joint_6_ik:
            ik_constraint = joint_6_ik.constraints.get("IK")
            if ik_constraint:
                ik_constraint.use_rotation = armature_obj.xarm_ik_track_rotation
                print(f"[xArm] IK track rotation: {ik_constraint.use_rotation}")
    except Exception as e:
        print(f"[xArm] Failed to update IK rotation tracking: {e}")

    # Force viewport redraw
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# ─────────────────────────────────────────────
# SETUP RIG OPERATOR
# ─────────────────────────────────────────────

class XARM_OT_SetupRig(bpy.types.Operator):
    """Create FK/IK animation rig from source twin collection"""
    bl_idname = "xarm.setup_rig"
    bl_label = "Setup Animation Rig"
    bl_description = "Create FK/IK rig with mode property system for dynamic switching"
    bl_options = {"REGISTER", "UNDO"}

    # Properties (replace CONFIGURATION constants from setup_animation_rig.py)
    source_collection_name: bpy.props.StringProperty(
        name="Source Collection",
        description="Collection to duplicate (e.g., uf850_twin)",
        default="uf850_twin"
    )

    output_collection_name: bpy.props.StringProperty(
        name="Output Collection",
        description="Name for new animation collection",
        default="uf850_animation"
    )

    source_suffix: bpy.props.StringProperty(
        name="Source Suffix",
        description="Suffix replaced in object/data names",
        default="_twin"
    )

    output_suffix: bpy.props.StringProperty(
        name="Output Suffix",
        description="New suffix for animation rig",
        default="_ani"
    )

    robot_type: bpy.props.EnumProperty(
        items=[
            ('uf850_twin', 'UF850', 'UFactory 850 robot'),
            ('ufxarm6_twin', 'xArm6', 'UFactory xArm6 robot')
        ],
        name="Robot Type",
        description="Robot configuration for joint limits and axes",
        default='uf850_twin'
    )

    default_mode: bpy.props.EnumProperty(
        items=[
            ('0', 'Full FK', 'Manual FK control (mode=0)'),
            ('1', 'Full IK', 'IK solver on all 6 joints (mode=1)'),
            ('2', 'Hybrid', 'FK base + IK tip (mode=2)')
        ],
        name="Default Mode",
        description="Initial mode for animation rig",
        default='1'
    )

    ik_chain_default: bpy.props.IntProperty(
        name="IK Chain Length",
        description="Initial IK chain length (6=full, 3=hybrid)",
        default=6,
        min=1,
        max=6
    )

    widget_scale: bpy.props.FloatProperty(
        name="Widget Scale",
        description="Control shape size multiplier",
        default=0.16,
        min=0.01,
        max=1.0
    )

    def execute(self, context):
        """
        Main operator logic.
        Based on setup_animation_rig.py:run() lines 157-623.
        """
        print("[xArm] Starting rig setup...")

        # Import robot config from core module
        from ..core.robot_config import XArmRigConfig

        # Get robot configuration
        try:
            robot_config = XArmRigConfig(self.robot_type)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Extract config values
        rotation_axes = robot_config.rotation_axes
        joint_limits_deg = robot_config.joint_limits_deg

        # ── 1. Find source collection ──────────────
        src_coll = bpy.data.collections.get(self.source_collection_name)
        if src_coll is None:
            self.report({'ERROR'}, f"Source collection '{self.source_collection_name}' not found")
            return {'CANCELLED'}

        if not any(o.type == 'ARMATURE' for o in src_coll.objects):
            self.report({'ERROR'}, f"No armature in '{self.source_collection_name}'")
            return {'CANCELLED'}

        # ── 2. Need VIEW_3D for operators ─────────
        area_3d = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
        if area_3d is None:
            self.report({'ERROR'}, "No 3D Viewport visible. Open one and retry.")
            return {'CANCELLED'}
        region = next((r for r in area_3d.regions if r.type == 'WINDOW'), None)

        # ── 3. Remove old output collection ───────
        old_coll = bpy.data.collections.get(self.output_collection_name)
        if old_coll:
            for obj in list(old_coll.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(old_coll)
            print(f"[INFO]  Removed existing '{self.output_collection_name}'")

        # ── 4. Create new output collection ───────
        out_coll = bpy.data.collections.new(self.output_collection_name)
        context.scene.collection.children.link(out_coll)
        print(f"[INFO]  Created collection '{self.output_collection_name}'")

        # ── 5. Duplicate all objects, rename ──────
        obj_map = {}
        for obj in src_coll.objects:
            new_obj = obj.copy()
            if obj.data is not None:
                new_obj.data = obj.data.copy()
                new_obj.data.name = obj.data.name.replace(self.source_suffix, self.output_suffix)
            new_name = obj.name.replace(self.source_suffix, self.output_suffix)
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

        # ── 7b. Make mesh objects unselectable ─────
        # Prevents accidental selection during animation (safer workflow)
        mesh_count = 0
        for new_obj in out_coll.objects:
            if new_obj.type == 'MESH':
                new_obj.hide_select = True
                mesh_count += 1
        if mesh_count > 0:
            print(f"[INFO]  Made {mesh_count} mesh objects unselectable")

        # ── 8. Locate renamed armature ────────────
        anim_obj = next((o for o in out_coll.objects if o.type == 'ARMATURE'), None)
        if anim_obj is None:
            self.report({'ERROR'}, "Armature not found after duplication")
            return {'CANCELLED'}
        print(f"[INFO]  Armature: '{anim_obj.name}'")

        expected = [f'joint_{i}' for i in range(1, 7)] + ['tcp']
        missing = [b for b in expected if b not in anim_obj.pose.bones]
        if missing:
            self.report({'ERROR'}, f"Missing bones in '{anim_obj.name}': {missing}")
            return {'CANCELLED'}

        # ── 9. Set as active ──────────────────────
        for obj in context.view_layer.objects:
            obj.select_set(False)
        anim_obj.select_set(True)
        context.view_layer.objects.active = anim_obj

        # ── 10. Edit Mode — add FK/IK chains + free tcp ──────────────
        with context.temp_override(area=area_3d, region=region):
            bpy.ops.object.mode_set(mode='EDIT')

            edit_bones = anim_obj.data.edit_bones
            root_parent = edit_bones['joint_1'].parent

            # Create _fk and _ik copies of every joint bone
            for i in range(1, 7):
                src = edit_bones[f'joint_{i}']
                for suffix in ('_fk', '_ik'):
                    b = edit_bones.new(f'joint_{i}{suffix}')
                    b.head = src.head.copy()
                    b.tail = src.tail.copy()
                    b.roll = src.roll
                    b.use_connect = False
                    b.use_deform = False

            # Parent FK chain
            edit_bones['joint_1_fk'].parent = root_parent
            for i in range(2, 7):
                edit_bones[f'joint_{i}_fk'].parent = edit_bones[f'joint_{i-1}_fk']

            # Parent IK chain
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
        with context.temp_override(area=area_3d, region=region):
            bpy.ops.object.mode_set(mode='POSE')

            pbones = anim_obj.pose.bones

            # Clear all constraints
            all_names = (
                [f'joint_{i}' for i in range(1, 7)] +
                [f'joint_{i}_fk' for i in range(1, 7)] +
                [f'joint_{i}_ik' for i in range(1, 7)] +
                ['tcp']
            )
            for name in all_names:
                if name in pbones:
                    for con in list(pbones[name].constraints):
                        pbones[name].constraints.remove(con)

            # Determine initial blend based on default mode
            default_mode_int = int(self.default_mode)
            ik_fk_default = 1.0 if default_mode_int >= 1 else 0.0

            # DEF bones: Copy Rotation from FK (1-blend) then from IK (blend)
            for i in range(1, 7):
                pb = pbones[f'joint_{i}']

                fk_con = pb.constraints.new('COPY_ROTATION')
                fk_con.name = 'Copy FK'
                fk_con.target = anim_obj
                fk_con.subtarget = f'joint_{i}_fk'
                fk_con.target_space = 'LOCAL'
                fk_con.owner_space = 'LOCAL'
                fk_con.influence = 1.0 - ik_fk_default

                ik_con = pb.constraints.new('COPY_ROTATION')
                ik_con.name = 'Copy IK'
                ik_con.target = anim_obj
                ik_con.subtarget = f'joint_{i}_ik'
                ik_con.target_space = 'LOCAL'
                ik_con.owner_space = 'LOCAL'
                ik_con.influence = ik_fk_default

            # IK solver on joint_6_ik targeting the free tcp bone
            ik_main = pbones['joint_6_ik'].constraints.new('IK')
            ik_main.name = 'IK'
            ik_main.target = anim_obj
            ik_main.subtarget = 'tcp'
            ik_main.chain_count = self.ik_chain_default
            ik_main.use_rotation = True

            print("[INFO]  Copy Rotation (FK + IK) added to DEF bones joint_1..6")
            print("[INFO]  IK solver on joint_6_ik → tcp bone (same armature)")

            # ── Apply IK locks and joint limits ──────
            for i in range(1, 7):
                axis_spec = rotation_axes[i - 1]
                limits_deg = joint_limits_deg[i - 1]

                # Parse axis
                if axis_spec.startswith('-'):
                    sign = -1
                    axis_char = axis_spec[1:]
                else:
                    sign = 1
                    axis_char = axis_spec

                # Convert limits to radians, flip if negative axis
                min_deg, max_deg = limits_deg
                if sign == -1:
                    min_rad = math.radians(-max_deg)
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
                axis_spec = rotation_axes[i - 1]
                limits_deg = joint_limits_deg[i - 1]

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

                # Lock location
                pb_fk.lock_location = (True, True, True)

                # Lock rotation on non-active axes
                pb_fk.lock_rotation = (
                    axis_char != 'X',
                    axis_char != 'Y',
                    axis_char != 'Z'
                )

                # Limit Rotation constraint
                limit = pb_fk.constraints.new('LIMIT_ROTATION')
                limit.name = 'Limit Rotation'
                limit.use_limit_x = (axis_char == 'X')
                limit.use_limit_y = (axis_char == 'Y')
                limit.use_limit_z = (axis_char == 'Z')
                limit.owner_space = 'LOCAL'

                if axis_char == 'X':
                    limit.min_x = min_rad
                    limit.max_x = max_rad
                elif axis_char == 'Y':
                    limit.min_y = min_rad
                    limit.max_y = max_rad
                else:  # 'Z'
                    limit.min_z = min_rad
                    limit.max_z = max_rad

            print("[INFO]  FK bone constraints: location locked, rotation locked, limits applied")

            bpy.ops.object.mode_set(mode='OBJECT')

        # ── 12. Mode property initialization ──────
        # Set EnumProperty (triggers update callback which creates custom property for drivers)
        anim_obj.xarm_mode = str(default_mode_int)
        print(f"[INFO]  Mode property: xarm_mode = {default_mode_int}")

        # IK rotation tracking (enabled by default)
        anim_obj.xarm_ik_track_rotation = True
        print(f"[INFO]  IK track rotation: True")

        # Internal blend property (driven by mode)
        anim_obj["ik_fk_blend"] = ik_fk_default
        anim_obj.id_properties_ui("ik_fk_blend").update(
            min=0.0, max=1.0,
            description="Auto-set by mode property (don't change manually)",
        )

        # Store robot config for export operators
        anim_obj["xarm_robot_type"] = self.robot_type

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
        var.targets[0].data_path = '["xarm_mode"]'

        print("[INFO]  Driver: xarm_mode → ik_fk_blend")

        # Driver: ik_fk_blend → constraint influences
        for i in range(1, 7):
            fk_path = f'pose.bones["joint_{i}"].constraints["Copy FK"].influence'
            ik_path = f'pose.bones["joint_{i}"].constraints["Copy IK"].influence'
            _add_driver(anim_obj, fk_path, '1 - blend', 'blend', '["ik_fk_blend"]')
            _add_driver(anim_obj, ik_path, 'blend', 'blend', '["ik_fk_blend"]')

        print("[INFO]  Drivers: ik_fk_blend → all joint constraints")

        # ── 14. Bone Collections (Blender 4.0+ API) ──────────────────
        arm_data = anim_obj.data

        for name in ('DEF', 'FK', 'IK'):
            existing = arm_data.collections.get(name)
            if existing:
                arm_data.collections.remove(existing)

        col_def = arm_data.collections.new('DEF')
        col_fk = arm_data.collections.new('FK')
        col_ik = arm_data.collections.new('IK')

        # Set visibility based on mode
        # Mode 0 (FK): FK visible, IK hidden
        # Mode 1 (IK): FK hidden, IK visible
        # Mode 2 (Hybrid): FK hidden, IK visible
        col_def.is_visible = False
        if default_mode_int == 0:
            col_fk.is_visible = True
            col_ik.is_visible = False
        else:  # mode 1 or 2
            col_fk.is_visible = False
            col_ik.is_visible = True

        for i in range(1, 7):
            col_def.assign(arm_data.bones[f'joint_{i}'])
            col_fk.assign(arm_data.bones[f'joint_{i}_fk'])
            col_ik.assign(arm_data.bones[f'joint_{i}_ik'])
        col_ik.assign(arm_data.bones['tcp'])

        fk_vis = "visible" if col_fk.is_visible else "hidden"
        ik_vis = "visible" if col_ik.is_visible else "hidden"
        print(f"[INFO]  Bone collections: DEF (hidden), FK ({fk_vis}), IK ({ik_vis})")

        # ── 15. Widgets + Colors ──────────────────
        ring_axes = ['Y', 'Z', 'Z', 'Y', 'Z', 'Y']
        pbones = anim_obj.pose.bones
        s = self.widget_scale

        # FK bones: blue rings
        for i in range(1, 7):
            pb = pbones[f'joint_{i}_fk']
            pb.custom_shape = _circle(f'WGT_joint_{i}_fk', axis=ring_axes[i-1])
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_scale_xyz = (s, s, s)
            pb.color.palette = 'THEME04'  # Blue

        # IK bones J1-J2: green rings (for hybrid mode manual rotation)
        for i in range(1, 3):
            pb = pbones[f'joint_{i}_ik']
            pb.custom_shape = _circle(f'WGT_joint_{i}_ik', axis=ring_axes[i-1])
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_scale_xyz = (s, s, s)
            pb.color.palette = 'THEME03'  # Green

        # IK bones J3-J6: no widget (controlled by IK solver)
        for i in range(3, 7):
            pbones[f'joint_{i}_ik'].custom_shape = None

        # tcp: orange cross
        tcp_pb = pbones['tcp']
        tcp_pb.custom_shape = _cross('WGT_tcp')
        tcp_pb.use_custom_shape_bone_size = False
        tcp_pb.custom_shape_scale_xyz = (s * 1.5, s * 1.5, s * 1.5)
        tcp_pb.color.palette = 'THEME09'  # Orange

        # DEF bones: no widget (hidden)
        for i in range(1, 7):
            pbones[f'joint_{i}'].custom_shape = None

        print("[INFO]  Widgets: FK rings (blue), IK J1-J2 rings (green), tcp cross (orange)")

        # ── Save reference in scene for later operators ──────
        context.scene.xarm_rig_armature = anim_obj
        context.scene.xarm_active_rig = anim_obj  # Auto-select new rig

        # ── Done ──────────────────────────────────
        print()
        print(f"[DONE]  Collection '{self.output_collection_name}' ready for animation")
        print(f"        Armature: '{anim_obj.name}'")
        print()

        self.report({'INFO'}, f"Created rig: {anim_obj.name} (mode={default_mode_int})")
        return {'FINISHED'}


# ─────────────────────────────────────────────
# UTILITY OPERATORS
# ─────────────────────────────────────────────

class XARM_OT_ResetTCP(bpy.types.Operator):
    """Reset TCP bone to home position (rest pose)"""
    bl_idname = "xarm.reset_tcp"
    bl_label = "Reset TCP to Home"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Only available if an armature is active"""
        return (context.active_object is not None and
                context.active_object.type == 'ARMATURE' and
                'tcp' in context.active_object.pose.bones)

    def execute(self, context):
        arm = context.active_object
        tcp_bone = arm.pose.bones.get('tcp')

        if not tcp_bone:
            self.report({'ERROR'}, "TCP bone not found")
            return {'CANCELLED'}

        # Clear location and rotation (reset to rest pose)
        tcp_bone.location = (0, 0, 0)
        tcp_bone.rotation_quaternion = (1, 0, 0, 0)
        tcp_bone.rotation_euler = (0, 0, 0)
        tcp_bone.scale = (1, 1, 1)

        # Update view
        context.view_layer.update()

        self.report({'INFO'}, "TCP reset to home position")
        print("[xArm] TCP bone reset to home position")
        return {'FINISHED'}


class XARM_OT_ClearAllTransforms(bpy.types.Operator):
    """Clear all transformations from FK, IK, and TCP bones (reset to rest pose)"""
    bl_idname = "xarm.clear_all_transforms"
    bl_label = "Clear All Transforms"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Only available if an armature is active"""
        return (context.active_object is not None and
                context.active_object.type == 'ARMATURE')

    def execute(self, context):
        arm = context.active_object
        pbones = arm.pose.bones

        # List of bone names to clear
        bone_names = []

        # FK bones
        for i in range(1, 7):
            bone_names.append(f'joint_{i}_fk')

        # IK bones
        for i in range(1, 7):
            bone_names.append(f'joint_{i}_ik')

        # TCP bone
        bone_names.append('tcp')

        cleared_count = 0
        for name in bone_names:
            if name in pbones:
                pb = pbones[name]

                # Clear location, rotation, scale
                pb.location = (0, 0, 0)
                pb.rotation_quaternion = (1, 0, 0, 0)
                pb.rotation_euler = (0, 0, 0)
                pb.scale = (1, 1, 1)

                cleared_count += 1

        # Update view
        context.view_layer.update()

        self.report({'INFO'}, f"Cleared transforms from {cleared_count} bones")
        print(f"[xArm] Cleared transforms from {cleared_count} control bones")
        return {'FINISHED'}
