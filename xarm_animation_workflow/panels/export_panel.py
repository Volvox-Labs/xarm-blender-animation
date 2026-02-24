"""
Export & Playback Panel

Provides UI for exporting animations to CSV and playing on robot.
"""

import bpy

from ..operators.play_csv import get_playback_status


class XARM_PT_Export(bpy.types.Panel):
    """Panel for CSV export and robot playback"""
    bl_label = "Export & Playback"
    bl_idname = "XARM_PT_EXPORT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # ── Section 1: Animation Source ──────────────────
        box = layout.box()
        box.label(text="Animation Source", icon='ARMATURE_DATA')

        col = box.column(align=True)

        # Armature selector dropdown
        col.prop(scene, 'xarm_active_rig', text='Export Rig')

        arm = scene.xarm_active_rig
        if arm and arm.name in bpy.data.objects:
            # Show robot type
            robot_type = arm.get("xarm_robot_type", "uf850_twin")
            robot_label = "UF850" if robot_type == "uf850_twin" else "xArm6"
            col.label(text=f"Robot: {robot_label}", icon='ARMATURE_DATA')
        else:
            col.label(text="Select rig to export", icon='INFO')

        # Export parameters
        col.separator()
        col.prop(scene.render, 'fps', text='FPS')

        row = col.row(align=True)
        row.prop(scene, 'frame_start', text='Start')
        row.prop(scene, 'frame_end', text='End')

        # ── Section 2: Export Buttons ──────────────────
        layout.separator()
        col = layout.column(align=True)

        # Export operators (enabled only if rig selected)
        if scene.xarm_active_rig and scene.xarm_active_rig.name in bpy.data.objects:
            col.operator('xarm.direct_export', text='Export CSV (No Bake)', icon='EXPORT')
            col.operator('xarm.bake_and_export', text='Bake & Export CSV', icon='RENDER_ANIMATION')
            col.separator()
            col.operator('xarm.clear_markers', text='Clear Violation Markers', icon='MARKER_HLT')
        else:
            col.label(text="Select rig to export", icon='INFO')

        # ── Section 3: Robot Playback ──────────────────
        layout.separator()
        box = layout.box()
        box.label(text="Robot Playback", icon='PLAY')

        col = box.column(align=True)

        # Robot settings
        col.prop(scene, 'xarm_robot_ip', text='Robot IP')
        col.prop(scene, 'xarm_playback_mode', text='Mode')
        col.prop(scene, 'xarm_playback_loops', text='Loops')

        col.separator()

        # CSV file selection
        row = col.row(align=True)
        row.operator('xarm.select_csv', text='Select CSV', icon='FILE_FOLDER')

        # Show selected file
        if scene.xarm_playback_csv_path:
            import os
            filename = os.path.basename(scene.xarm_playback_csv_path)
            col.label(text=f"File: {filename}", icon='FILE')
        else:
            col.label(text="No CSV selected", icon='INFO')

        col.separator()

        # Playback status
        status = get_playback_status()
        if status['running']:
            # Show progress
            progress_box = col.box()
            progress_box.alert = True

            if status['total'] > 0:
                progress = status['progress'] / status['total']
                progress_box.label(text=f"Playing: {status['progress']}/{status['total']} frames")
                progress_box.progress(factor=progress, type='BAR')
            else:
                progress_box.label(text=status['message'] or "Playing...")

            col.operator('xarm.stop_playback', text='STOP', icon='CANCEL')
        else:
            # Play button
            col.operator('xarm.play_csv', text='Play CSV on Robot', icon='PLAY')

        # Warning
        col.separator()
        warn_box = col.box()
        warn_box.label(text="Ensure workspace is clear!", icon='ERROR')


def register():
    bpy.utils.register_class(XARM_PT_Export)


def unregister():
    bpy.utils.unregister_class(XARM_PT_Export)
