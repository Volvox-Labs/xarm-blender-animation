"""
Rig Setup & Control Panel

Provides UI for creating animation rigs and dynamically switching modes.
"""

import bpy


class XARM_PT_RigSetup(bpy.types.Panel):
    """Panel for rig setup and mode control"""
    bl_label = "Rig Setup & Control"
    bl_idname = "XARM_PT_RIG_SETUP"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # ── Section 1: Create Animation Rig ──────────────────
        box = layout.box()
        box.label(text="Create Animation Rig", icon='ARMATURE_DATA')

        col = box.column(align=True)
        col.prop(scene, 'xarm_source_collection_name', text='Source')
        col.prop(scene, 'xarm_output_collection_name', text='Output')
        col.prop(scene, 'xarm_robot_type', text='Robot')
        col.prop(scene, 'xarm_default_mode', text='Default Mode')
        col.prop(scene, 'xarm_ik_chain_default', text='IK Chain')
        col.prop(scene, 'xarm_widget_scale', text='Widget Scale')

        # Setup Rig button
        col.separator()
        op = col.operator('xarm.setup_rig', text='Setup Rig', icon='ADD')
        # Pre-fill operator properties from scene properties
        op.source_collection_name = scene.xarm_source_collection_name
        op.output_collection_name = scene.xarm_output_collection_name
        op.robot_type = scene.xarm_robot_type
        op.default_mode = scene.xarm_default_mode
        op.ik_chain_default = scene.xarm_ik_chain_default
        op.widget_scale = scene.xarm_widget_scale

        # ── Section 2: Mode Control ──────────────────
        # Only show if rig exists
        if scene.xarm_rig_armature:
            layout.separator()
            box = layout.box()
            box.label(text="Mode Control", icon='MODIFIER')

            arm = scene.xarm_rig_armature

            # Check if armature still exists in scene
            if arm.name in bpy.data.objects:
                col = box.column(align=True)

                # Mode selector (expand=True for radio buttons)
                col.prop(arm, 'xarm_mode', expand=True)

                # IK rotation tracking toggle
                col.separator()
                col.prop(arm, 'xarm_ik_track_rotation', text="Track TCP Rotation", toggle=True)

                # Status display
                col.separator()
                if "xarm_mode" in arm:
                    mode = int(arm["xarm_mode"])

                    # Bone visibility status
                    fk_coll = arm.data.collections.get("FK")
                    ik_coll = arm.data.collections.get("IK")
                    if fk_coll and ik_coll:
                        fk_visible = fk_coll.is_visible
                        ik_visible = ik_coll.is_visible
                        col.label(text=f"FK: {'Visible' if fk_visible else 'Hidden'}, IK: {'Visible' if ik_visible else 'Hidden'}",
                                 icon='HIDE_OFF' if (fk_visible or ik_visible) else 'HIDE_ON')

                    # IK chain status
                    ik_bone = arm.pose.bones.get("joint_6_ik")
                    if ik_bone:
                        ik_con = ik_bone.constraints.get("IK")
                        if ik_con:
                            col.label(text=f"IK Chain Length: {ik_con.chain_count}", icon='CONSTRAINT_BONE')

                    # Mode description
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

                # ── Utility Buttons ──────────────────
                layout.separator()
                box = layout.box()
                box.label(text="Utilities", icon='TOOL_SETTINGS')

                col = box.column(align=True)
                col.operator('xarm.reset_tcp', text='Reset TCP to Home', icon='HOME')
                col.operator('xarm.clear_all_transforms', text='Clear All Transforms', icon='LOOP_BACK')

            else:
                box.label(text="Armature reference invalid", icon='ERROR')
                box.label(text="Delete and create new rig")


def register():
    bpy.utils.register_class(XARM_PT_RigSetup)


def unregister():
    bpy.utils.unregister_class(XARM_PT_RigSetup)
