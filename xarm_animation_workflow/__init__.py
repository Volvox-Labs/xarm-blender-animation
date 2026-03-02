"""
xArm Animation Workflow - Blender Addon
========================================
Complete workflow for xArm robot animation: rig setup, mode switching, baking, and CSV export/playback.

Consolidates standalone scripts into unified addon with UI parameters.
"""

import bpy

bl_info = {
    "name": "xArm Animation Workflow",
    "author": "Generated from standalone scripts",
    "description": "Complete xArm robot animation workflow: rig, export, playback",
    "blender": (5, 0, 1),
    "version": (1, 0, 0),
    "category": "3D View",
    "location": "View3D > Sidebar > xArm Animation",
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
}

# Import modules
from .operators import setup_rig, export_operators, play_csv
from .panels import rig_panel, export_panel


def register():
    """Register addon classes and properties"""
    print("[xArm Animation Workflow] Registering addon...")

    # ── Scene properties (rig setup parameters) ──────────
    bpy.types.Scene.xarm_source_collection_name = bpy.props.StringProperty(
        name="Source Collection",
        description="Collection to duplicate (e.g., uf850_twin)",
        default="uf850_twin"
    )

    bpy.types.Scene.xarm_output_collection_name = bpy.props.StringProperty(
        name="Output Collection",
        description="Name for new animation collection",
        default="uf850_animation"
    )

    bpy.types.Scene.xarm_robot_type = bpy.props.EnumProperty(
        items=[
            ('uf850_twin', 'UF850', 'UFactory 850 robot'),
            ('ufxarm6_twin', 'xArm6', 'UFactory xArm6 robot')
        ],
        name="Robot Type",
        default='uf850_twin'
    )

    bpy.types.Scene.xarm_default_mode = bpy.props.EnumProperty(
        items=[
            ('0', 'Full FK', 'Manual FK control'),
            ('1', 'Full IK', 'IK solver on all 6 joints'),
            ('2', 'Hybrid', 'FK base + IK tip')
        ],
        name="Default Mode",
        default='1'
    )

    bpy.types.Scene.xarm_ik_chain_default = bpy.props.IntProperty(
        name="IK Chain Length",
        description="Initial IK chain length (6=full IK, 4=hybrid, 0=FK only)",
        default=6,
        min=0,
        max=6
    )

    bpy.types.Scene.xarm_widget_scale = bpy.props.FloatProperty(
        name="Widget Scale",
        description="Control shape size multiplier",
        default=0.16,
        min=0.01,
        max=1.0
    )

    # Armature reference (set after rig creation)
    bpy.types.Scene.xarm_rig_armature = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Animation Rig",
        description="Created animation armature"
    )

    # Active collection selector (for mode control and export)
    # The armature is automatically found within the selected collection
    bpy.types.Scene.xarm_active_collection = bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Active Collection",
        description="Select collection containing the animation rig"
    )

    # ── Robot playback properties ──────────
    bpy.types.Scene.xarm_robot_ip = bpy.props.StringProperty(
        name="Robot IP",
        description="xArm robot IP address",
        default="localhost"
    )

    bpy.types.Scene.xarm_playback_mode = bpy.props.EnumProperty(
        name="Playback Mode",
        items=[
            ('cued', 'Cued (Safe)', 'Wait for each position - safe and precise'),
            ('servo', 'Servo (Fast)', 'Streaming mode - real-time playback')
        ],
        default='cued'
    )

    bpy.types.Scene.xarm_playback_loops = bpy.props.IntProperty(
        name="Loops",
        description="Number of times to play animation",
        default=1,
        min=1,
        max=100
    )

    bpy.types.Scene.xarm_last_export_path = bpy.props.StringProperty(
        name="Last Export",
        description="Path to last exported CSV file",
        default=""
    )

    bpy.types.Scene.xarm_playback_csv_path = bpy.props.StringProperty(
        name="Playback CSV",
        description="Selected CSV file for robot playback",
        default=""
    )

    # ── Export settings ──────────
    bpy.types.Scene.xarm_speed_warning_threshold = bpy.props.FloatProperty(
        name="Speed Warning %",
        description="Warn when joint speed exceeds this percentage of max (180 deg/s)",
        default=90.0,
        min=50.0,
        max=100.0,
        subtype='PERCENTAGE'
    )

    # ── Object properties (per-armature settings) ──────────
    # Mode selection with update callback for dynamic switching
    bpy.types.Object.xarm_mode = bpy.props.EnumProperty(
        name="Mode",
        items=[
            ('0', 'Full FK', 'Manual FK control'),
            ('1', 'Full IK', 'IK solver on all 6 joints'),
            ('2', 'Hybrid', 'FK base + IK tip')
        ],
        default='1',
        update=setup_rig.xarm_mode_update_callback
    )

    # IK rotation tracking toggle
    bpy.types.Object.xarm_ik_track_rotation = bpy.props.BoolProperty(
        name="Track TCP Rotation",
        description="Enable IK solver to track TCP rotation (not just position)",
        default=True,
        update=setup_rig.xarm_ik_rotation_update_callback
    )

    # ── Register operators ──────────
    bpy.utils.register_class(setup_rig.XARM_OT_SetupRig)
    bpy.utils.register_class(setup_rig.XARM_OT_ResetTCP)
    bpy.utils.register_class(setup_rig.XARM_OT_ClearAllTransforms)
    bpy.utils.register_class(setup_rig.XARM_OT_RefreshWidgets)
    bpy.utils.register_class(export_operators.XARM_OT_ExportReport)
    bpy.utils.register_class(export_operators.XARM_OT_ClearMarkers)
    bpy.utils.register_class(export_operators.XARM_OT_DirectExport)
    bpy.utils.register_class(export_operators.XARM_OT_BakeAndExport)
    bpy.utils.register_class(play_csv.XARM_OT_SelectCSV)
    bpy.utils.register_class(play_csv.XARM_OT_PlayCSV)
    bpy.utils.register_class(play_csv.XARM_OT_StopPlayback)

    # ── Register panels ──────────
    bpy.utils.register_class(rig_panel.XARM_PT_RigSetup)
    bpy.utils.register_class(export_panel.XARM_PT_Export)

    print("[xArm Animation Workflow] Registration complete")


def unregister():
    """Unregister addon classes and properties"""
    print("[xArm Animation Workflow] Unregistering addon...")

    # Unregister in reverse order
    bpy.utils.unregister_class(export_panel.XARM_PT_Export)
    bpy.utils.unregister_class(rig_panel.XARM_PT_RigSetup)
    bpy.utils.unregister_class(play_csv.XARM_OT_StopPlayback)
    bpy.utils.unregister_class(play_csv.XARM_OT_PlayCSV)
    bpy.utils.unregister_class(play_csv.XARM_OT_SelectCSV)
    bpy.utils.unregister_class(export_operators.XARM_OT_BakeAndExport)
    bpy.utils.unregister_class(export_operators.XARM_OT_DirectExport)
    bpy.utils.unregister_class(export_operators.XARM_OT_ClearMarkers)
    bpy.utils.unregister_class(export_operators.XARM_OT_ExportReport)
    bpy.utils.unregister_class(setup_rig.XARM_OT_RefreshWidgets)
    bpy.utils.unregister_class(setup_rig.XARM_OT_ClearAllTransforms)
    bpy.utils.unregister_class(setup_rig.XARM_OT_ResetTCP)
    bpy.utils.unregister_class(setup_rig.XARM_OT_SetupRig)

    # Delete properties
    del bpy.types.Scene.xarm_speed_warning_threshold
    del bpy.types.Scene.xarm_playback_csv_path
    del bpy.types.Scene.xarm_last_export_path
    del bpy.types.Scene.xarm_playback_loops
    del bpy.types.Scene.xarm_playback_mode
    del bpy.types.Scene.xarm_robot_ip
    del bpy.types.Object.xarm_ik_track_rotation
    del bpy.types.Object.xarm_mode
    del bpy.types.Scene.xarm_active_collection
    del bpy.types.Scene.xarm_rig_armature
    del bpy.types.Scene.xarm_widget_scale
    del bpy.types.Scene.xarm_ik_chain_default
    del bpy.types.Scene.xarm_default_mode
    del bpy.types.Scene.xarm_robot_type
    del bpy.types.Scene.xarm_output_collection_name
    del bpy.types.Scene.xarm_source_collection_name

    print("[xArm Animation Workflow] Unregistration complete")


if __name__ == "__main__":
    register()
