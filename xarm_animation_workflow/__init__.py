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


def _safe_register_class(cls):
    """Register class, recovering from stale Blender reload state."""
    existing = getattr(bpy.types, cls.__name__, None)
    if existing is not None:
        try:
            bpy.utils.unregister_class(existing)
        except Exception:
            pass

    try:
        bpy.utils.register_class(cls)
    except ValueError as e:
        if "already registered as a subclass" in str(e):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
            bpy.utils.register_class(cls)
        else:
            raise


def _safe_unregister_class(cls):
    """Unregister class if registered; ignore stale-state errors."""
    existing = getattr(bpy.types, cls.__name__, None)
    if existing is not None:
        try:
            bpy.utils.unregister_class(existing)
            return
        except Exception:
            pass

    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        pass


def _safe_del_attr(owner, name: str):
    """Delete RNA property only if present."""
    if hasattr(owner, name):
        delattr(owner, name)


OPERATOR_CLASSES = (
    setup_rig.XARM_OT_SetupRig,
    setup_rig.XARM_OT_ResetTCP,
    setup_rig.XARM_OT_ClearAllTransforms,
    setup_rig.XARM_OT_RefreshWidgets,
    setup_rig.XARM_OT_ApplyToolLength,
    export_operators.XARM_OT_AddSceneRobotSlot,
    export_operators.XARM_OT_RemoveSceneRobotSlot,
    export_operators.XARM_OT_SelectSceneExportDir,
    export_operators.XARM_OT_ExportSceneBundle,
    export_operators.XARM_OT_SelectCollisionExportDir,
    export_operators.XARM_OT_ExportCollisionURDF,
    export_operators.XARM_OT_ExportReport,
    export_operators.XARM_OT_ClearMarkers,
    export_operators.XARM_OT_ValidateAnimation,
    export_operators.XARM_OT_DirectExport,
    export_operators.XARM_OT_BakeAndExport,
    play_csv.XARM_OT_SelectCSV,
    play_csv.XARM_OT_PlayCSV,
    play_csv.XARM_OT_StopPlayback,
)

PANEL_CLASSES = (
    rig_panel.XARM_PT_RigSetup,
    rig_panel.XARM_PT_RigControl,
    export_panel.XARM_PT_Validation,
    export_panel.XARM_PT_SingleExport,
    export_panel.XARM_PT_SceneExport,
    export_panel.XARM_PT_CollisionExport,
    export_panel.XARM_PT_Playback,
)


def register():
    """Register addon classes and properties"""
    print("[xArm Animation Workflow] Registering addon...")
    _safe_register_class(export_operators.XARM_PG_SceneRobotSlot)

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

    # Tool length offset in mm (added to 30mm base joint_6 length)
    bpy.types.Scene.xarm_tool_length_mm = bpy.props.FloatProperty(
        name="Tool Length (mm)",
        description="Tool length offset in mm. Joint 6 bone length = 30mm + this value",
        default=0.0,
        min=0.0,
        max=500.0,
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
    bpy.types.Scene.xarm_tcp_speed_limit_mm_s = bpy.props.FloatProperty(
        name="TCP Speed Limit (mm/s)",
        description="Warn when TCP speed exceeds this limit in mm/s (0-1000)",
        default=1000.0,
        min=0.0,
        max=1000.0,
    )

    # Scene export settings (multi-robot bundle)
    bpy.types.Scene.xarm_scene_export_name = bpy.props.StringProperty(
        name="Scene Name",
        description="Scene name stored in metadata and used for output folder name",
        default="scene_export"
    )

    bpy.types.Scene.xarm_scene_export_dir = bpy.props.StringProperty(
        name="Scene Export Root",
        description="Root folder for scene export bundles",
        default="",
        subtype='DIR_PATH'
    )

    bpy.types.Scene.xarm_scene_export_slots = bpy.props.CollectionProperty(
        name="Scene Robot Slots",
        type=export_operators.XARM_PG_SceneRobotSlot
    )

    bpy.types.Scene.xarm_scene_export_active_slot = bpy.props.IntProperty(
        name="Active Scene Slot",
        default=0,
        min=0
    )

    # Collision URDF export settings
    bpy.types.Scene.xarm_collision_collection = bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Collision Collection",
        description="Collection containing collision meshes to export"
    )

    bpy.types.Scene.xarm_collision_urdf_name = bpy.props.StringProperty(
        name="Collision URDF Name",
        description="URDF robot name and output folder name",
        default="site_collision"
    )

    bpy.types.Scene.xarm_collision_export_dir = bpy.props.StringProperty(
        name="Collision Export Root",
        description="Root folder for collision URDF bundle export",
        default="",
        subtype='DIR_PATH'
    )

    bpy.types.Scene.xarm_collision_last_export_path = bpy.props.StringProperty(
        name="Last Collision Export",
        description="Path to last exported collision URDF file",
        default=""
    )

    # Default collision collection if available (guard restricted startup context)
    data_api = getattr(bpy, "data", None)
    collections = getattr(data_api, "collections", None) if data_api else None
    scenes = getattr(data_api, "scenes", None) if data_api else None
    if collections is not None and scenes is not None:
        default_collision = collections.get(export_operators.COLLISION_DEFAULT_COLLECTION)
        if default_collision:
            for scene in scenes:
                if not scene.xarm_collision_collection:
                    scene.xarm_collision_collection = default_collision

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

    # ── Register operators ──────────
    for cls in OPERATOR_CLASSES:
        _safe_register_class(cls)

    # ── Register panels ──────────
    for cls in PANEL_CLASSES:
        _safe_register_class(cls)

    print("[xArm Animation Workflow] Registration complete")


def unregister():
    """Unregister addon classes and properties"""
    print("[xArm Animation Workflow] Unregistering addon...")

    # Unregister in reverse order
    for cls in reversed(PANEL_CLASSES):
        _safe_unregister_class(cls)
    for cls in reversed(OPERATOR_CLASSES):
        _safe_unregister_class(cls)

    # Delete properties
    _safe_del_attr(bpy.types.Scene, "xarm_collision_last_export_path")
    _safe_del_attr(bpy.types.Scene, "xarm_collision_export_dir")
    _safe_del_attr(bpy.types.Scene, "xarm_collision_urdf_name")
    _safe_del_attr(bpy.types.Scene, "xarm_collision_collection")
    _safe_del_attr(bpy.types.Scene, "xarm_scene_export_active_slot")
    _safe_del_attr(bpy.types.Scene, "xarm_scene_export_slots")
    _safe_del_attr(bpy.types.Scene, "xarm_scene_export_dir")
    _safe_del_attr(bpy.types.Scene, "xarm_scene_export_name")
    _safe_del_attr(bpy.types.Scene, "xarm_tcp_speed_limit_mm_s")
    _safe_del_attr(bpy.types.Scene, "xarm_speed_warning_threshold")
    _safe_del_attr(bpy.types.Scene, "xarm_playback_csv_path")
    _safe_del_attr(bpy.types.Scene, "xarm_last_export_path")
    _safe_del_attr(bpy.types.Scene, "xarm_playback_loops")
    _safe_del_attr(bpy.types.Scene, "xarm_playback_mode")
    _safe_del_attr(bpy.types.Scene, "xarm_robot_ip")
    _safe_del_attr(bpy.types.Object, "xarm_follow_leader")
    _safe_del_attr(bpy.types.Object, "xarm_follow_enabled")
    _safe_del_attr(bpy.types.Object, "xarm_ik_track_rotation")
    _safe_del_attr(bpy.types.Object, "xarm_mode")
    _safe_del_attr(bpy.types.Scene, "xarm_active_collection")
    _safe_del_attr(bpy.types.Scene, "xarm_rig_armature")
    _safe_del_attr(bpy.types.Scene, "xarm_tool_length_mm")
    _safe_del_attr(bpy.types.Scene, "xarm_widget_scale")
    _safe_del_attr(bpy.types.Scene, "xarm_ik_chain_default")
    _safe_del_attr(bpy.types.Scene, "xarm_default_mode")
    _safe_del_attr(bpy.types.Scene, "xarm_robot_type")
    _safe_del_attr(bpy.types.Scene, "xarm_output_collection_name")
    _safe_del_attr(bpy.types.Scene, "xarm_source_collection_name")
    _safe_unregister_class(export_operators.XARM_PG_SceneRobotSlot)

    print("[xArm Animation Workflow] Unregistration complete")


if __name__ == "__main__":
    register()
