# Follow Mode & Tool Length Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add leader/follower TCP constraint mode for dual-robot IK workflows, add a tool length setting that adjusts joint_6 bone length across all scene rigs, and reorganize the UI panels for clarity.

**Architecture:** Follow mode extends the existing IK mode control system by adding bone constraints (Copy Location + Copy Rotation) to a follower robot's TCP bone targeting a leader robot's TCP bone. Tool length is a scene-level property that modifies joint_6 bone tail position (all 3 variants: DEF, FK, IK) in edit mode. UI is reorganized by splitting "Rig Setup & Control" into two panels: "Rig Setup" (creation) and "Rig Control" (runtime mode switching, follow mode, tool length, utilities).

**Tech Stack:** Blender Python API (bpy), bone constraints, edit mode bone manipulation.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `xarm_animation_workflow/operators/setup_rig.py` | Modify | Add follow mode operators (toggle, callbacks), tool length operator |
| `xarm_animation_workflow/panels/rig_panel.py` | Modify | Split into two panels, add follow mode UI, add tool length UI |
| `xarm_animation_workflow/__init__.py` | Modify | Register new properties (follow mode, tool length), register new operators/panels |

No new files needed - all changes extend existing modules.

---

## Chunk 1: Follow Mode

### Task 1: Add Follow Mode Properties and Callbacks

**Files:**
- Modify: `xarm_animation_workflow/__init__.py` (register section, ~line 287-306)
- Modify: `xarm_animation_workflow/operators/setup_rig.py` (after `xarm_ik_rotation_update_callback`, ~line 276)

- [ ] **Step 1.1: Add follow mode properties to `__init__.py`**

Add these per-armature properties in `register()`, after the existing `xarm_ik_track_rotation` property (line 306):

```python
# Follow mode: leader/follower TCP constraint pairing
bpy.types.Object.xarm_follow_enabled = bpy.props.BoolProperty(
    name="Follow Mode",
    description="When enabled, this robot's TCP follows the leader robot's TCP",
    default=False,
    update=setup_rig.xarm_follow_update_callback
)

bpy.types.Object.xarm_follow_leader = bpy.props.PointerProperty(
    type=bpy.types.Object,
    name="Leader Robot",
    description="Leader robot armature whose TCP this robot will follow",
    poll=setup_rig.xarm_rig_poll
)
```

Add matching cleanup in `unregister()`:

```python
_safe_del_attr(bpy.types.Object, "xarm_follow_leader")
_safe_del_attr(bpy.types.Object, "xarm_follow_enabled")
```

- [ ] **Step 1.2: Implement follow mode callback in `setup_rig.py`**

Add after `xarm_ik_rotation_update_callback` (~line 276):

```python
# Constraint names used by follow mode
_FOLLOW_COPY_LOC = "TCP Follow Location"
_FOLLOW_COPY_ROT = "TCP Follow Rotation"


def _remove_follow_constraints(armature_obj):
    """Remove follow mode constraints from TCP bone."""
    tcp_bone = armature_obj.pose.bones.get("tcp")
    if tcp_bone is None:
        return
    for name in (_FOLLOW_COPY_LOC, _FOLLOW_COPY_ROT):
        con = tcp_bone.constraints.get(name)
        if con:
            tcp_bone.constraints.remove(con)
            print(f"[xArm] Removed constraint '{name}' from tcp")


def _apply_follow_constraints(follower_obj, leader_obj):
    """Add Copy Location + Copy Rotation constraints to follower TCP targeting leader TCP."""
    tcp_bone = follower_obj.pose.bones.get("tcp")
    if tcp_bone is None:
        print("[xArm] Follow mode: tcp bone not found on follower")
        return False

    leader_tcp = leader_obj.pose.bones.get("tcp")
    if leader_tcp is None:
        print("[xArm] Follow mode: tcp bone not found on leader")
        return False

    # Remove existing follow constraints first (idempotent)
    _remove_follow_constraints(follower_obj)

    # Copy Location: all axes, world space
    loc_con = tcp_bone.constraints.new('COPY_LOCATION')
    loc_con.name = _FOLLOW_COPY_LOC
    loc_con.target = leader_obj
    loc_con.subtarget = "tcp"
    loc_con.owner_space = 'WORLD'
    loc_con.target_space = 'WORLD'
    loc_con.influence = 1.0
    print(f"[xArm] Follow: added Copy Location (world) -> {leader_obj.name}/tcp")

    # Copy Rotation: invert X, local space
    rot_con = tcp_bone.constraints.new('COPY_ROTATION')
    rot_con.name = _FOLLOW_COPY_ROT
    rot_con.target = leader_obj
    rot_con.subtarget = "tcp"
    rot_con.owner_space = 'LOCAL'
    rot_con.target_space = 'LOCAL'
    rot_con.invert_x = True
    rot_con.invert_y = False
    rot_con.invert_z = False
    rot_con.influence = 1.0
    print(f"[xArm] Follow: added Copy Rotation (local, invert X) -> {leader_obj.name}/tcp")

    return True


def xarm_follow_update_callback(armature_obj, context):
    """Called when xarm_follow_enabled changes. Adds or removes follow constraints."""
    if not hasattr(armature_obj, 'xarm_follow_enabled'):
        return

    if armature_obj.xarm_follow_enabled:
        leader = armature_obj.xarm_follow_leader
        if leader is None:
            print("[xArm] Follow mode: no leader selected, disabling")
            # Can't set property inside callback without recursion guard
            # Just remove constraints and warn
            _remove_follow_constraints(armature_obj)
            return

        if leader == armature_obj:
            print("[xArm] Follow mode: can't follow self, disabling")
            _remove_follow_constraints(armature_obj)
            return

        # Ensure follower is in IK mode (follow only works with IK)
        current_mode = int(armature_obj.xarm_mode) if hasattr(armature_obj, 'xarm_mode') else 0
        if current_mode == 0:
            print("[xArm] Follow mode: switching follower to IK mode (required for follow)")
            armature_obj.xarm_mode = '1'

        # Ensure leader is also in IK mode (TCP must be standalone target)
        leader_mode = int(leader.xarm_mode) if hasattr(leader, 'xarm_mode') else 0
        if leader_mode == 0:
            print("[xArm] Follow mode: switching leader to IK mode (TCP must be standalone)")
            leader.xarm_mode = '1'

        _apply_follow_constraints(armature_obj, leader)
    else:
        _remove_follow_constraints(armature_obj)

    # Force viewport redraw
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()
```

- [ ] **Step 1.3: Update `xarm_mode_update_callback` to disable follow on FK switch**

In `setup_rig.py`, at the end of `xarm_mode_update_callback` (before the viewport redraw loop, ~line 248), add:

```python
    # Disable follow mode when switching to FK (follow requires IK)
    if mode == 0 and hasattr(armature_obj, 'xarm_follow_enabled') and armature_obj.xarm_follow_enabled:
        _remove_follow_constraints(armature_obj)
        armature_obj["xarm_follow_enabled"] = 0  # Use custom prop to avoid callback recursion
        print("[xArm] Follow mode disabled (switched to FK)")
```

- [ ] **Step 1.4: Verify follow mode properties load without errors**

Open Blender, enable the addon. In the Python console, verify:
```python
bpy.types.Object.xarm_follow_enabled  # Should exist
bpy.types.Object.xarm_follow_leader   # Should exist
```

- [ ] **Step 1.5: Commit**

```bash
git add xarm_animation_workflow/operators/setup_rig.py xarm_animation_workflow/__init__.py
git commit -m "feat: add follow mode properties and constraint logic for leader/follower TCP"
```

---

### Task 2: Add Follow Mode UI

**Files:**
- Modify: `xarm_animation_workflow/panels/rig_panel.py` (~line 68-71, after Track TCP Rotation)

- [ ] **Step 2.1: Add follow mode section to rig panel**

In `rig_panel.py`, after the Track TCP Rotation toggle (line 70), add the follow mode UI:

```python
            # ── Follow Mode (IK only) ──────────────────
            col.separator()
            col.label(text="Follow Mode", icon='LINKED')

            # Leader selector
            col.prop(arm, 'xarm_follow_leader', text="Leader")

            # Follow toggle (only enable if leader is set and rig is in IK)
            follow_row = col.row(align=True)
            current_mode = int(arm.get("xarm_mode", 1))
            has_leader = arm.xarm_follow_leader is not None
            follow_row.enabled = has_leader and current_mode >= 1
            follow_row.prop(arm, 'xarm_follow_enabled', text="Follow Leader TCP", toggle=True)

            if arm.xarm_follow_enabled and arm.xarm_follow_leader:
                col.label(text=f"Following: {arm.xarm_follow_leader.name}", icon='CHECKMARK')
            elif not has_leader:
                col.label(text="Select a leader robot first", icon='INFO')
            elif current_mode == 0:
                col.label(text="Follow requires IK or Hybrid mode", icon='INFO')
```

- [ ] **Step 2.2: Verify UI renders correctly**

Open Blender, go to sidebar > xArm Animation > Rig Setup & Control. With an IK rig selected, verify:
- Leader dropdown appears, filtered to xArm armatures only
- Follow toggle is disabled when no leader is selected
- Follow toggle is disabled in FK mode
- Enabling follow adds constraints to TCP bone
- Disabling follow removes constraints

- [ ] **Step 2.3: Commit**

```bash
git add xarm_animation_workflow/panels/rig_panel.py
git commit -m "feat: add follow mode UI in rig control panel"
```

---

## Chunk 2: Tool Length

### Task 3: Add Tool Length Property and Operator

**Files:**
- Modify: `xarm_animation_workflow/__init__.py` (register section)
- Modify: `xarm_animation_workflow/operators/setup_rig.py` (new operator)

- [ ] **Step 3.1: Add tool length scene property in `__init__.py`**

Add in `register()`, after the `xarm_widget_scale` property (line 155):

```python
# Tool length offset in mm (added to 30mm base joint_6 length)
bpy.types.Scene.xarm_tool_length_mm = bpy.props.FloatProperty(
    name="Tool Length (mm)",
    description="Tool length offset in mm. Joint 6 bone length = 30mm + this value",
    default=0.0,
    min=0.0,
    max=500.0,
    subtype='DISTANCE',
    unit='NONE',
)
```

Add cleanup in `unregister()`:

```python
_safe_del_attr(bpy.types.Scene, "xarm_tool_length_mm")
```

- [ ] **Step 3.2: Add `XARM_OT_ApplyToolLength` operator in `setup_rig.py`**

Add after the `XARM_OT_RefreshWidgets` class:

```python
class XARM_OT_ApplyToolLength(bpy.types.Operator):
    """Apply tool length to all xArm rigs in the scene (modifies joint_6 bone length)"""
    bl_idname = "xarm.apply_tool_length"
    bl_label = "Apply Tool Length"
    bl_options = {'REGISTER', 'UNDO'}

    # Base joint_6 length in Blender units (meters). 30mm = 0.03m
    _BASE_J6_LENGTH_M = 0.03

    def execute(self, context):
        scene = context.scene
        tool_mm = scene.xarm_tool_length_mm
        # Total length in meters: 30mm base + tool length
        total_length_m = self._BASE_J6_LENGTH_M + (tool_mm / 1000.0)

        # Find animation rigs only (have FK/IK chains from Setup Rig).
        # Excludes raw asset/sim rigs like uf850_twin which lack _fk/_ik bones.
        xarm_armatures = [
            obj for obj in scene.objects
            if (obj.type == 'ARMATURE'
                and obj.get("xarm_robot_type") is not None
                and obj.data.bones.get("joint_6_fk") is not None)
        ]

        if not xarm_armatures:
            self.report({'WARNING'}, "No xArm rigs found in scene")
            return {'CANCELLED'}

        area_3d = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
        if area_3d is None:
            self.report({'ERROR'}, "No 3D Viewport visible")
            return {'CANCELLED'}
        region = next((r for r in area_3d.regions if r.type == 'WINDOW'), None)

        modified_count = 0
        for arm_obj in xarm_armatures:
            # Must be active object to enter edit mode
            context.view_layer.objects.active = arm_obj
            arm_obj.select_set(True)

            with context.temp_override(area=area_3d, region=region):
                bpy.ops.object.mode_set(mode='EDIT')

                edit_bones = arm_obj.data.edit_bones
                for suffix in ('', '_fk', '_ik'):
                    bone_name = f'joint_6{suffix}'
                    bone = edit_bones.get(bone_name)
                    if bone is None:
                        continue

                    # Extend tail along the bone's local axis (head->tail direction)
                    direction = (bone.tail - bone.head).normalized()
                    bone.tail = bone.head + direction * total_length_m

                bpy.ops.object.mode_set(mode='OBJECT')

            arm_obj.select_set(False)
            modified_count += 1
            print(f"[xArm] Tool length: {arm_obj.name} joint_6 set to {total_length_m*1000:.1f}mm")

        self.report({'INFO'}, f"Applied tool length ({tool_mm:.0f}mm) to {modified_count} rigs")
        return {'FINISHED'}
```

- [ ] **Step 3.3: Register the new operator in `__init__.py`**

Add `setup_rig.XARM_OT_ApplyToolLength` to `OPERATOR_CLASSES` tuple (after `XARM_OT_RefreshWidgets`):

```python
OPERATOR_CLASSES = (
    setup_rig.XARM_OT_SetupRig,
    setup_rig.XARM_OT_ResetTCP,
    setup_rig.XARM_OT_ClearAllTransforms,
    setup_rig.XARM_OT_RefreshWidgets,
    setup_rig.XARM_OT_ApplyToolLength,  # <-- add this
    ...
)
```

- [ ] **Step 3.4: Commit**

```bash
git add xarm_animation_workflow/operators/setup_rig.py xarm_animation_workflow/__init__.py
git commit -m "feat: add tool length property and operator to adjust joint_6 bone length"
```

---

## Chunk 3: UI Reorganization

### Task 4: Split Rig Panel into Setup + Control

**Files:**
- Modify: `xarm_animation_workflow/panels/rig_panel.py` (rewrite)
- Modify: `xarm_animation_workflow/__init__.py` (register new panel class)

The current `XARM_PT_RigSetup` panel is doing two jobs: rig creation (one-time) and runtime control (frequent). Split into:

1. **`XARM_PT_RigSetup`** (bl_order=0) — "Rig Setup": Create rig, tool length (scene-wide settings)
2. **`XARM_PT_RigControl`** (bl_order=1) — "Rig Control": Mode switching, follow mode, utilities (per-rig runtime)

All export panels shift bl_order by +1.

- [ ] **Step 4.1: Rewrite `rig_panel.py` with two panels**

```python
"""
Rig Panels

Panel 1: Rig Setup — create animation rigs and scene-wide settings.
Panel 2: Rig Control — per-rig mode switching, follow mode, utilities.
"""

import bpy

from ..operators.setup_rig import get_armature_from_collection


class XARM_PT_RigSetup(bpy.types.Panel):
    """Panel for creating animation rigs and scene-wide settings."""
    bl_label = "Rig Setup"
    bl_idname = "XARM_PT_RIG_SETUP"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # ── Create Animation Rig ──────────────────
        box = layout.box()
        box.label(text="Create Animation Rig", icon='ARMATURE_DATA')

        col = box.column(align=True)
        col.prop(scene, 'xarm_source_collection_name', text='Source')
        col.prop(scene, 'xarm_output_collection_name', text='Output')
        col.prop(scene, 'xarm_robot_type', text='Robot')
        col.prop(scene, 'xarm_default_mode', text='Default Mode')
        col.prop(scene, 'xarm_ik_chain_default', text='IK Chain')
        col.prop(scene, 'xarm_widget_scale', text='Widget Scale')

        col.separator()
        op = col.operator('xarm.setup_rig', text='Setup Rig', icon='ADD')
        op.source_collection_name = scene.xarm_source_collection_name
        op.output_collection_name = scene.xarm_output_collection_name
        op.robot_type = scene.xarm_robot_type
        op.default_mode = scene.xarm_default_mode
        op.ik_chain_default = scene.xarm_ik_chain_default
        op.widget_scale = scene.xarm_widget_scale

        # ── Tool Length (scene-wide) ──────────────────
        layout.separator()
        box = layout.box()
        box.label(text="Tool Length", icon='ARROW_LEFTRIGHT')

        col = box.column(align=True)
        col.prop(scene, 'xarm_tool_length_mm', text='Tool Offset (mm)')
        col.label(text=f"Joint 6 total: {30 + scene.xarm_tool_length_mm:.1f} mm")
        col.separator()
        col.operator('xarm.apply_tool_length', text='Apply to All Rigs', icon='CHECKMARK')


class XARM_PT_RigControl(bpy.types.Panel):
    """Panel for per-rig mode switching, follow mode, and utilities."""
    bl_label = "Rig Control"
    bl_idname = "XARM_PT_RIG_CONTROL"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # ── Rig Selector ──────────────────
        col = layout.column(align=True)
        col.prop(scene, 'xarm_active_collection', text='Rig Collection')

        arm = get_armature_from_collection(scene.xarm_active_collection)

        if arm and arm.name in bpy.data.objects:
            col.label(text=f"Armature: {arm.name}", icon='ARMATURE_DATA')

            # ── Mode Control ──────────────────
            layout.separator()
            box = layout.box()
            box.label(text="Mode", icon='MODIFIER')

            col = box.column(align=True)
            col.prop(arm, 'xarm_mode', expand=True)

            col.separator()
            col.prop(arm, 'xarm_ik_track_rotation', text="Track TCP Rotation", toggle=True)

            # ── Follow Mode (IK only) ──────────────────
            layout.separator()
            box = layout.box()
            box.label(text="Follow Mode", icon='LINKED')

            col = box.column(align=True)
            col.prop(arm, 'xarm_follow_leader', text="Leader")

            follow_row = col.row(align=True)
            current_mode = int(arm.get("xarm_mode", 1))
            has_leader = arm.xarm_follow_leader is not None
            follow_row.enabled = has_leader and current_mode >= 1
            follow_row.prop(arm, 'xarm_follow_enabled', text="Follow Leader TCP", toggle=True)

            if arm.xarm_follow_enabled and arm.xarm_follow_leader:
                col.label(text=f"Following: {arm.xarm_follow_leader.name}", icon='CHECKMARK')
            elif not has_leader:
                col.label(text="Select a leader robot first", icon='INFO')
            elif current_mode == 0:
                col.label(text="Follow requires IK or Hybrid mode", icon='INFO')

            # ── Base Transform ──────────────────
            collection = scene.xarm_active_collection
            base_obj = None
            if collection:
                for obj in collection.objects:
                    if '_base' in obj.name:
                        base_obj = obj
                        break

            if base_obj:
                layout.separator()
                box = layout.box()
                box.label(text="Base Transform", icon='EMPTY_AXIS')
                col = box.column(align=True)
                col.prop(base_obj, 'location', text='Position')
                col.prop(base_obj, 'rotation_euler', text='Rotation')

            # ── Status ──────────────────
            layout.separator()
            box = layout.box()
            box.label(text="Status", icon='INFO')
            col = box.column(align=True)

            if "xarm_mode" in arm:
                mode = int(arm["xarm_mode"])

                fk_coll = arm.data.collections.get("FK")
                ik_coll = arm.data.collections.get("IK")
                if fk_coll and ik_coll:
                    fk_visible = fk_coll.is_visible
                    ik_visible = ik_coll.is_visible
                    col.label(text=f"FK: {'Visible' if fk_visible else 'Hidden'}, IK: {'Visible' if ik_visible else 'Hidden'}",
                             icon='HIDE_OFF' if (fk_visible or ik_visible) else 'HIDE_ON')

                ik_bone = arm.pose.bones.get("joint_6_ik")
                if ik_bone:
                    ik_con = ik_bone.constraints.get("IK")
                    if ik_con:
                        col.label(text=f"IK Chain Length: {ik_con.chain_count}", icon='CONSTRAINT_BONE')

                col.separator()
                if mode == 0:
                    col.label(text="Mode: Full FK", icon='ORIENTATION_LOCAL')
                    col.label(text="-> Rotate blue FK bones manually")
                elif mode == 1:
                    col.label(text="Mode: Full IK", icon='CONSTRAINT')
                    col.label(text="-> Move/rotate orange TCP target")
                elif mode == 2:
                    col.label(text="Mode: Hybrid (IK chain=4)", icon='CON_ROTLIKE')
                    col.label(text="-> Rotate green J1-J2, move TCP")

            # ── Utilities ──────────────────
            layout.separator()
            box = layout.box()
            box.label(text="Utilities", icon='TOOL_SETTINGS')

            col = box.column(align=True)
            col.operator('xarm.reset_tcp', text='Reset TCP to Home', icon='HOME')
            col.operator('xarm.clear_all_transforms', text='Clear All Transforms', icon='LOOP_BACK')
            col.separator()
            col.operator('xarm.refresh_widgets', text='Refresh Control Widgets', icon='OUTLINER_OB_ARMATURE')

        elif scene.xarm_active_collection:
            col.separator()
            col.label(text="No armature found in collection", icon='ERROR')
            col.label(text="(Collection needs xArm rig)")
        else:
            col.separator()
            col.label(text="Select a rig collection", icon='INFO')


def register():
    bpy.utils.register_class(XARM_PT_RigSetup)
    bpy.utils.register_class(XARM_PT_RigControl)


def unregister():
    bpy.utils.unregister_class(XARM_PT_RigControl)
    bpy.utils.unregister_class(XARM_PT_RigSetup)
```

- [ ] **Step 4.2: Update `__init__.py` panel registration**

Update `PANEL_CLASSES` to include the new panel:

```python
PANEL_CLASSES = (
    rig_panel.XARM_PT_RigSetup,
    rig_panel.XARM_PT_RigControl,       # <-- add new panel
    export_panel.XARM_PT_SingleExport,
    export_panel.XARM_PT_Validation,
    export_panel.XARM_PT_SceneExport,
    export_panel.XARM_PT_Playback,
    export_panel.XARM_PT_CollisionExport,
)
```

- [ ] **Step 4.3: Update export panel bl_order values and default-closed states**

In `export_panel.py`, reorder panels and set all to `DEFAULT_CLOSED` except Rig Control. New order: Validation → Single Export → Scene Export → Collision Export → Playback.

- `XARM_PT_Validation`: bl_order = 2, add `bl_options = {'DEFAULT_CLOSED'}` (was bl_order=2)
- `XARM_PT_SingleExport`: bl_order = 3, add `bl_options = {'DEFAULT_CLOSED'}` (was bl_order=1)
- `XARM_PT_SceneExport`: bl_order = 4, add `bl_options = {'DEFAULT_CLOSED'}` (was bl_order=3)
- `XARM_PT_CollisionExport`: bl_order = 5, add `bl_options = {'DEFAULT_CLOSED'}` (was bl_order=5)
- `XARM_PT_Playback`: bl_order = 6, add `bl_options = {'DEFAULT_CLOSED'}` (was bl_order=4)

- [ ] **Step 4.4: Update `PANEL_CLASSES` order in `__init__.py`**

Registration order must match the new bl_order:

```python
PANEL_CLASSES = (
    rig_panel.XARM_PT_RigSetup,            # 0 - closed
    rig_panel.XARM_PT_RigControl,           # 1 - OPEN
    export_panel.XARM_PT_Validation,        # 2 - closed
    export_panel.XARM_PT_SingleExport,      # 3 - closed
    export_panel.XARM_PT_SceneExport,       # 4 - closed
    export_panel.XARM_PT_CollisionExport,   # 5 - closed
    export_panel.XARM_PT_Playback,          # 6 - closed
)
```

- [ ] **Step 4.5: Manual verification in Blender**

Open Blender, verify sidebar shows panels in order:
1. **Rig Setup** (collapsed) — Create rig + Tool Length
2. **Rig Control** (open by default) — Mode, Follow, Base Transform, Status, Utilities
3. **Validation** (collapsed)
4. **Single Export** (collapsed)
5. **Scene Export** (collapsed)
6. **Collision Export** (collapsed)
7. **Playback** (collapsed)

- [ ] **Step 4.5: Commit**

```bash
git add xarm_animation_workflow/panels/rig_panel.py xarm_animation_workflow/panels/export_panel.py xarm_animation_workflow/__init__.py
git commit -m "refactor: split rig panel into Setup + Control, add follow mode and tool length UI"
```

---

## Summary of UI Layout (After Changes)

```
xArm Animation (Sidebar Tab)
├── Rig Setup (collapsed)
│   ├── Create Animation Rig
│   │   ├── Source / Output / Robot / Mode / IK Chain / Widget Scale
│   │   └── [Setup Rig] button
│   └── Tool Length
│       ├── Tool Offset (mm) slider
│       ├── "Joint 6 total: XX.X mm" label
│       └── [Apply to All Rigs] button
│
├── Rig Control (OPEN by default)
│   ├── Rig Collection selector
│   ├── Mode (Full FK / Full IK / Hybrid radio)
│   ├── Track TCP Rotation toggle
│   ├── Follow Mode
│   │   ├── Leader dropdown (filtered to xArm rigs)
│   │   ├── [Follow Leader TCP] toggle
│   │   └── Status label
│   ├── Base Transform (position / rotation)
│   ├── Status (visibility, IK chain, mode description)
│   └── Utilities (Reset TCP, Clear All, Refresh Widgets)
│
├── Validation (collapsed)
├── Single Export (collapsed)
├── Scene Export (collapsed)
├── Collision Export (collapsed)
└── Playback (collapsed)
```

## Constraint Details (Follow Mode)

When follow mode is enabled on a follower robot:

| Constraint | Type | Target | Space | Options |
|-----------|------|--------|-------|---------|
| TCP Follow Location | COPY_LOCATION | leader/tcp | Owner: WORLD, Target: WORLD | All axes |
| TCP Follow Rotation | COPY_ROTATION | leader/tcp | Owner: LOCAL, Target: LOCAL | Invert X only |

When follow mode is disabled: both constraints are removed from the follower's TCP bone.
