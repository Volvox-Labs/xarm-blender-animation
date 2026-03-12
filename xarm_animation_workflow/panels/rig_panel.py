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
                    col.label(text="→ Rotate blue FK bones manually")
                elif mode == 1:
                    col.label(text="Mode: Full IK", icon='CONSTRAINT')
                    col.label(text="→ Move/rotate orange TCP target")
                elif mode == 2:
                    col.label(text="Mode: Hybrid (IK chain=4)", icon='CON_ROTLIKE')
                    col.label(text="→ Rotate green J1-J2, move TCP")

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
