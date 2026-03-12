"""
Export Panels

Provides UI for single CSV export, scene bundle export, and robot playback.
"""

import bpy

from ..operators.play_csv import get_playback_status
from ..operators.setup_rig import get_armature_from_collection


def _draw_animation_source(layout, scene):
    box = layout.box()
    box.label(text="Animation Source", icon='ARMATURE_DATA')

    col = box.column(align=True)
    col.prop(scene, 'xarm_active_collection', text='Rig Collection')

    arm = get_armature_from_collection(scene.xarm_active_collection)
    if arm and arm.name in bpy.data.objects:
        col.label(text=f"Armature: {arm.name}", icon='ARMATURE_DATA')
        robot_type = arm.get("xarm_robot_type", "uf850_twin")
        robot_label = "UF850" if robot_type == "uf850_twin" else "xArm6"
        col.label(text=f"Robot: {robot_label}")
    elif scene.xarm_active_collection:
        col.label(text="No armature found in collection", icon='ERROR')
    else:
        col.label(text="Select rig collection to export", icon='INFO')

    return arm


class XARM_PT_SingleExport(bpy.types.Panel):
    """Panel for exporting one robot rig to CSV."""
    bl_label = "Single Export"
    bl_idname = "XARM_PT_SINGLE_EXPORT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        arm = _draw_animation_source(layout, scene)

        layout.separator()
        col = layout.column(align=True)
        if arm and arm.name in bpy.data.objects:
            col.operator('xarm.bake_and_export', text='Bake & Export CSV', icon='RENDER_ANIMATION')
        else:
            col.label(text="Select rig collection to export", icon='INFO')


class XARM_PT_Validation(bpy.types.Panel):
    """Panel for timeline/action validation without export."""
    bl_label = "Validation"
    bl_idname = "XARM_PT_VALIDATION"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        arm = _draw_animation_source(layout, scene)

        box = layout.box()
        box.label(text="Validation Settings", icon='CHECKMARK')
        col = box.column(align=True)
        col.prop(scene.render, 'fps', text='FPS')
        row = col.row(align=True)
        row.prop(scene, 'frame_start', text='Start')
        row.prop(scene, 'frame_end', text='End')
        col.separator()
        col.prop(scene, 'xarm_speed_warning_threshold', text='Joint Speed Warn %')
        col.prop(scene, 'xarm_tcp_speed_limit_mm_s', text='TCP Limit (mm/s)')
        col.label(text="Joint max reference: 180 deg/s", icon='INFO')
        col.label(text="TCP limit reference: 0-1000 mm/s", icon='INFO')

        layout.separator()
        actions = layout.column(align=True)
        if arm and arm.name in bpy.data.objects:
            actions.operator('xarm.validate_animation', text='Validate Current Animation', icon='CHECKMARK')
            actions.operator('xarm.clear_markers', text='Clear Violation Markers', icon='MARKER_HLT')
        else:
            actions.label(text="Select rig collection to validate", icon='INFO')


class XARM_PT_SceneExport(bpy.types.Panel):
    """Panel for exporting scene bundle metadata + CSV files."""
    bl_label = "Scene Export"
    bl_idname = "XARM_PT_SCENE_EXPORT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Scene Bundle Settings", icon='OUTLINER_COLLECTION')

        col = box.column(align=True)
        col.prop(scene, 'xarm_scene_export_name', text='Scene Name')

        row = col.row(align=True)
        row.prop(scene, 'xarm_scene_export_dir', text='Save Root')
        row.operator('xarm.select_scene_export_dir', text='', icon='FILE_FOLDER')

        col.separator()
        col.label(text=f"Frame Range: {scene.frame_start} - {scene.frame_end}")
        col.label(text=f"FPS: {scene.render.fps}")

        col.separator()
        header = col.row(align=True)
        header.label(text="Robot Slots")
        header.operator('xarm.add_scene_robot_slot', text='', icon='ADD')

        if scene.xarm_scene_export_slots:
            for i, slot in enumerate(scene.xarm_scene_export_slots):
                slot_box = col.box()
                row = slot_box.row(align=True)
                row.label(text=f"Robot {i + 1}")
                remove_op = row.operator('xarm.remove_scene_robot_slot', text='', icon='X')
                remove_op.index = i

                slot_box.prop(slot, 'robot_id', text='ID')
                slot_box.prop(slot, 'collection', text='Collection')

                if slot.collection:
                    slot_arm = get_armature_from_collection(slot.collection)
                    if slot_arm and slot_arm.name in bpy.data.objects:
                        slot_box.label(text=f"Armature: {slot_arm.name}", icon='ARMATURE_DATA')
                        if slot_arm.animation_data and slot_arm.animation_data.action:
                            slot_box.label(text=f"Active: {slot_arm.animation_data.action.name}", icon='ACTION')
                        else:
                            slot_box.label(text="Action: none", icon='ERROR')
                    else:
                        slot_box.label(text="No xArm armature in collection", icon='ERROR')
        else:
            col.label(text="No robot slots added", icon='INFO')

        col.separator()
        col.operator('xarm.export_scene_bundle', text='Export Scene Bundle', icon='EXPORT')


class XARM_PT_Playback(bpy.types.Panel):
    """Panel for playing CSV on robot."""
    bl_label = "Playback"
    bl_idname = "XARM_PT_PLAYBACK"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 4

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Robot Playback", icon='PLAY')

        col = box.column(align=True)
        col.prop(scene, 'xarm_robot_ip', text='Robot IP')
        col.prop(scene, 'xarm_playback_mode', text='Mode')
        col.prop(scene, 'xarm_playback_loops', text='Loops')

        col.separator()
        row = col.row(align=True)
        row.operator('xarm.select_csv', text='Select CSV', icon='FILE_FOLDER')

        if scene.xarm_playback_csv_path:
            import os
            filename = os.path.basename(scene.xarm_playback_csv_path)
            col.label(text=f"File: {filename}", icon='FILE')
        else:
            col.label(text="No CSV selected", icon='INFO')

        col.separator()
        status = get_playback_status()
        if status['running']:
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
            col.operator('xarm.play_csv', text='Play CSV on Robot', icon='PLAY')

        col.separator()
        warn_box = col.box()
        warn_box.label(text="Ensure workspace is clear!", icon='ERROR')


class XARM_PT_CollisionExport(bpy.types.Panel):
    """Panel for exporting collision collection to URDF bundle."""
    bl_label = "Collision Export"
    bl_idname = "XARM_PT_COLLISION_EXPORT"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'xArm Animation'
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        box = layout.box()
        box.label(text="Collision URDF Export", icon='MESH_CUBE')
        col = box.column(align=True)

        col.prop(scene, 'xarm_collision_collection', text='Collection')
        col.prop(scene, 'xarm_collision_urdf_name', text='URDF Name')

        row = col.row(align=True)
        row.prop(scene, 'xarm_collision_export_dir', text='Save Root')
        row.operator('xarm.select_collision_export_dir', text='', icon='FILE_FOLDER')

        collection = scene.xarm_collision_collection or bpy.data.collections.get("collision")
        if collection:
            mesh_count = len([obj for obj in collection.all_objects if obj.type == 'MESH'])
            col.label(text=f"Meshes: {mesh_count}", icon='OUTLINER_OB_MESH')
        else:
            col.label(text="No collision collection selected", icon='INFO')

        col.separator()
        col.operator('xarm.export_collision_urdf', text='Export Collision URDF', icon='EXPORT')

        if scene.xarm_collision_last_export_path:
            import os
            filename = os.path.basename(scene.xarm_collision_last_export_path)
            col.separator()
            col.label(text=f"Last: {filename}", icon='FILE')


def register():
    bpy.utils.register_class(XARM_PT_SingleExport)
    bpy.utils.register_class(XARM_PT_Validation)
    bpy.utils.register_class(XARM_PT_SceneExport)
    bpy.utils.register_class(XARM_PT_Playback)
    bpy.utils.register_class(XARM_PT_CollisionExport)


def unregister():
    bpy.utils.unregister_class(XARM_PT_CollisionExport)
    bpy.utils.unregister_class(XARM_PT_Playback)
    bpy.utils.unregister_class(XARM_PT_SceneExport)
    bpy.utils.unregister_class(XARM_PT_Validation)
    bpy.utils.unregister_class(XARM_PT_SingleExport)
