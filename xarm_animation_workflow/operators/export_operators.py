"""
Export Operators

Provides operators for exporting animations to CSV format.
- DirectExport: Export current animation without baking
- BakeAndExport: Bake animation first, then export
"""

import bpy
import os
import json
import math
import struct
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Tuple, List, Dict, Set, Optional, Any

from ..core.robot_config import XArmRigConfig
from ..core.bone_utils import BoneAngleExtractor
from ..core.csv_export import SpeedCalculator, CSVExporter
from .setup_rig import get_armature_from_collection

COLLISION_DEFAULT_COLLECTION = "collision"
COLLISION_FIXED_LINK_NAME = "new_link"


# ─────────────────────────────────────────────────────────────
# Export Report Popup
# ─────────────────────────────────────────────────────────────

class XARM_OT_ExportReport(bpy.types.Operator):
    """Show export validation report"""
    bl_idname = "xarm.export_report"
    bl_label = "Export Report"
    bl_options = {'INTERNAL'}

    # Store report data (set before invoking)
    _report_data: Dict = {}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        layout = self.layout
        data = XARM_OT_ExportReport._report_data

        # Header
        row = layout.row()
        if data.get('has_errors'):
            row.alert = True
            row.label(text="Export completed with issues", icon='ERROR')
        elif data.get('has_warnings'):
            row.label(text="Export completed with warnings", icon='INFO')
        else:
            row.label(text="Export successful", icon='CHECKMARK')

        layout.separator()

        # Max speed info
        max_speed = data.get('max_speed_pct', 0)
        if max_speed > 0:
            box = layout.box()
            box.label(text=f"Peak Speed: {max_speed:.1f}% of max (180 deg/s)", icon='SORTTIME')

        # Speed violations
        speed_frames = data.get('speed_frames', {})
        if speed_frames:
            box = layout.box()
            box.label(text=f"Speed Violations ({len(speed_frames)} frames)", icon='ERROR')

            col = box.column(align=True)
            # Show first 10 frames with details
            for i, (frame, joints) in enumerate(sorted(speed_frames.items())[:10]):
                joint_str = ", ".join([f"J{j+1}:{v:.0f}°/s" for j, v in joints])
                col.label(text=f"Frame {frame}: {joint_str}")

            if len(speed_frames) > 10:
                col.label(text=f"... and {len(speed_frames) - 10} more frames")

            # Tip
            box.label(text="Tip: Markers added to timeline at violation frames", icon='MARKER')

        # Joint limit violations
        limit_frames = data.get('limit_frames', {})
        if limit_frames:
            box = layout.box()
            box.alert = True
            box.label(text=f"Joint Limit Violations ({len(limit_frames)} frames)", icon='ERROR')

            col = box.column(align=True)
            for i, (frame, errors) in enumerate(sorted(limit_frames.items())[:10]):
                col.label(text=f"Frame {frame}: {errors[0]}")

            if len(limit_frames) > 10:
                col.label(text=f"... and {len(limit_frames) - 10} more frames")

        # Summary
        layout.separator()
        box = layout.box()
        box.label(text=f"Exported: {data.get('filepath', 'unknown')}")
        box.label(text=f"Frames: {data.get('num_frames', 0)} | FPS: {data.get('fps', 30)}")


def clear_xarm_markers(context) -> int:
    """Clear all xarm violation markers from timeline.

    Returns:
        Number of markers removed
    """
    scene = context.scene
    markers_to_remove = [m for m in scene.timeline_markers if m.name.startswith("xarm_")]
    count = len(markers_to_remove)
    for m in markers_to_remove:
        scene.timeline_markers.remove(m)
    return count


def add_violation_markers(context, speed_frames: Dict[int, List], limit_frames: Dict[int, List], clear_existing: bool = True):
    """Add timeline markers at frames with violations.

    Args:
        context: Blender context
        speed_frames: Dict of frame -> [(joint_idx, velocity), ...]
        limit_frames: Dict of frame -> [error_msg, ...]
        clear_existing: Remove existing xarm markers first
    """
    # Clear existing xarm markers
    if clear_existing:
        clear_xarm_markers(context)

    scene = context.scene

    # Add speed violation markers (yellow/orange)
    for frame in speed_frames:
        scene.timeline_markers.new(f"xarm_speed_{frame}", frame=frame)

    # Add limit violation markers (named differently)
    for frame in limit_frames:
        if frame not in speed_frames:  # Don't duplicate
            scene.timeline_markers.new(f"xarm_limit_{frame}", frame=frame)

    total = len(speed_frames) + len(set(limit_frames) - set(speed_frames))
    if total > 0:
        print(f"[INFO] Added {total} violation markers to timeline")


def _sanitize_name(name: str, fallback: str = "scene_export") -> str:
    """Sanitize names for folders/files."""
    safe = "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in name.strip())
    safe = safe.strip("_.")
    return safe or fallback


def _find_robot_root_object(collection: bpy.types.Collection, armature: bpy.types.Object) -> bpy.types.Object:
    """Prefer base object for transform metadata, fallback to armature."""
    for obj in collection.objects:
        if "_base" in obj.name:
            return obj
    return armature


def _get_transform_xyz(obj: bpy.types.Object) -> Tuple[List[float], List[float]]:
    """Extract world transform as translate and rotateXYZ (degrees)."""
    loc = obj.matrix_world.to_translation()
    rot = obj.matrix_world.to_euler('XYZ')

    translate = [float(loc.x), float(loc.y), float(loc.z)]
    rotate_xyz = [
        float(math.degrees(float(rot.x))),
        float(math.degrees(float(rot.y))),
        float(math.degrees(float(rot.z))),
    ]
    return translate, rotate_xyz


def _export_armature_action_to_csv(
    armature: bpy.types.Object,
    filepath: str,
    start_frame: int,
    end_frame: int,
    fps: float,
    max_speed_pct: float,
    warning_threshold: float,
) -> Dict[str, Any]:
    """Export currently active armature action to CSV and return summary."""
    if not armature.animation_data or not armature.animation_data.action:
        raise ValueError(f"Armature '{armature.name}' has no active action")

    robot_type = armature.get("xarm_robot_type", "uf850_twin")
    config = XArmRigConfig(robot_type)

    extractor = BoneAngleExtractor(armature.name, config)
    speed_calc = SpeedCalculator(
        max_velocity_deg_s=config.max_velocity_deg_s,
        fps=fps,
        max_speed_override=max_speed_pct,
    )
    exporter = CSVExporter(filepath, include_tcp=False)

    speed_frames: Dict[int, List] = {}
    limit_frames: Dict[int, List] = {}
    prev_angles = None
    max_observed_speed_pct = 0.0

    for frame in range(start_frame, end_frame + 1):
        angles = extractor.get_joint_angles(frame)

        is_valid, errors = extractor.validate_limits(angles, frame)
        if not is_valid:
            limit_frames[frame] = errors

        if prev_angles is None:
            speed_pct = 0.0
            velocities = [0.0] * 6
        else:
            speed_pct, velocities = speed_calc.calculate_speed(prev_angles, angles)

            actual_pct = (max(velocities) / config.max_velocity_deg_s) * 100.0
            max_observed_speed_pct = max(max_observed_speed_pct, actual_pct)

            threshold_vel = config.max_velocity_deg_s * warning_threshold
            violations = []
            for j, vel in enumerate(velocities):
                if vel > threshold_vel:
                    violations.append((j, vel))
            if violations:
                speed_frames[frame] = violations

        time_s = (frame - start_frame) / fps
        exporter.add_frame(frame, time_s, angles, speed_pct)
        prev_angles = angles

    exporter.write()

    return {
        "num_frames": end_frame - start_frame + 1,
        "speed_frames": speed_frames,
        "limit_frames": limit_frames,
        "max_speed_pct": max_observed_speed_pct,
        "action_name": armature.animation_data.action.name,
        "robot_type": robot_type,
    }


def _bake_armature_action_to_csv(
    context: bpy.types.Context,
    armature: bpy.types.Object,
    filepath: str,
    start_frame: int,
    end_frame: int,
    fps: float,
    max_speed_pct: float,
    warning_threshold: float,
) -> Dict[str, Any]:
    """Bake source armature action to a temp rig, then export baked result to CSV."""
    baked_armature = None
    baked_action = None
    baked_data = None
    original_active_object = context.view_layer.objects.active
    source_action_name = armature.animation_data.action.name if armature.animation_data and armature.animation_data.action else ""

    try:
        baked_armature = armature.copy()
        baked_data = armature.data.copy()
        baked_armature.data = baked_data
        baked_armature.name = f"{armature.name}_SCENE_BAKE_TEMP"
        baked_armature.data.name = f"{armature.data.name}_SCENE_BAKE_TEMP"

        target_collection = armature.users_collection[0] if armature.users_collection else context.scene.collection
        target_collection.objects.link(baked_armature)

        if not baked_armature.animation_data:
            baked_armature.animation_data_create()
        baked_armature.animation_data.action = armature.animation_data.action

        for obj in context.view_layer.objects:
            obj.select_set(False)
        baked_armature.select_set(True)
        context.view_layer.objects.active = baked_armature

        area_3d = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
        if area_3d is None:
            raise RuntimeError("No 3D Viewport visible. Open one and retry.")
        region = next((r for r in area_3d.regions if r.type == 'WINDOW'), None)

        with context.temp_override(area=area_3d, region=region):
            bpy.ops.object.mode_set(mode='POSE')
            bpy.ops.pose.select_all(action='SELECT')
            bpy.ops.nla.bake(
                frame_start=start_frame,
                frame_end=end_frame,
                only_selected=False,
                visual_keying=True,
                clear_constraints=True,
                clear_parents=False,
                use_current_action=False,
                bake_types={'POSE'},
            )
            bpy.ops.object.mode_set(mode='OBJECT')

        baked_action = baked_armature.animation_data.action

        summary = _export_armature_action_to_csv(
            armature=baked_armature,
            filepath=filepath,
            start_frame=start_frame,
            end_frame=end_frame,
            fps=fps,
            max_speed_pct=max_speed_pct,
            warning_threshold=warning_threshold,
        )
        if source_action_name:
            summary["action_name"] = source_action_name
        return summary
    finally:
        if baked_armature and baked_armature.name in bpy.data.objects:
            try:
                bpy.data.objects.remove(baked_armature, do_unlink=True)
            except Exception:
                pass

        if baked_action and baked_action.name in bpy.data.actions:
            try:
                bpy.data.actions.remove(baked_action)
            except Exception:
                pass

        if baked_data and baked_data.users == 0 and baked_data.name in bpy.data.armatures:
            try:
                bpy.data.armatures.remove(baked_data)
            except Exception:
                pass

        if original_active_object and original_active_object.name in bpy.data.objects:
            context.view_layer.objects.active = original_active_object


class XARM_PG_SceneRobotSlot(bpy.types.PropertyGroup):
    """One robot entry in scene-level export."""
    robot_id: bpy.props.StringProperty(
        name="Robot ID",
        description="Unique robot identifier in scene metadata",
        default="robot1",
    )
    collection: bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Rig Collection",
        description="Collection containing one xArm animation rig",
    )


class XARM_OT_AddSceneRobotSlot(bpy.types.Operator):
    """Add a robot slot for scene export."""
    bl_idname = "xarm.add_scene_robot_slot"
    bl_label = "Add Robot Slot"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        slot = scene.xarm_scene_export_slots.add()
        slot.robot_id = f"robot{len(scene.xarm_scene_export_slots)}"
        if scene.xarm_active_collection:
            slot.collection = scene.xarm_active_collection
        scene.xarm_scene_export_active_slot = max(0, len(scene.xarm_scene_export_slots) - 1)
        self.report({'INFO'}, "Added robot export slot")
        return {'FINISHED'}


class XARM_OT_RemoveSceneRobotSlot(bpy.types.Operator):
    """Remove one robot slot from scene export list."""
    bl_idname = "xarm.remove_scene_robot_slot"
    bl_label = "Remove Robot Slot"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        scene = context.scene
        slots = scene.xarm_scene_export_slots

        if self.index < 0 or self.index >= len(slots):
            self.report({'ERROR'}, "Invalid slot index")
            return {'CANCELLED'}

        slots.remove(self.index)

        if len(slots) == 0:
            scene.xarm_scene_export_active_slot = 0
        else:
            scene.xarm_scene_export_active_slot = min(scene.xarm_scene_export_active_slot, len(slots) - 1)

        self.report({'INFO'}, "Removed robot export slot")
        return {'FINISHED'}


class XARM_OT_SelectSceneExportDir(bpy.types.Operator):
    """Select folder for scene export bundle."""
    bl_idname = "xarm.select_scene_export_dir"
    bl_label = "Select Scene Export Folder"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(
        name="Folder",
        description="Folder used as root for scene export bundles",
        subtype='DIR_PATH',
    )

    def invoke(self, context, event):
        scene = context.scene
        if scene.xarm_scene_export_dir:
            self.filepath = scene.xarm_scene_export_dir
        else:
            self.filepath = bpy.path.abspath("//")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        selected = bpy.path.abspath(self.filepath)
        if not selected:
            self.report({'ERROR'}, "No folder selected")
            return {'CANCELLED'}

        if os.path.isfile(selected):
            selected = os.path.dirname(selected)

        context.scene.xarm_scene_export_dir = selected
        self.report({'INFO'}, f"Scene export folder set: {selected}")
        return {'FINISHED'}


def _indent_xml(elem: ET.Element, level: int = 0):
    """Pretty-print XML tree in-place."""
    indent = "\n" + ("  " * level)
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        for child in elem:
            _indent_xml(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def _format_xyz(values: Tuple[float, float, float]) -> str:
    return f"{values[0]:.5f} {values[1]:.5f} {values[2]:.5f}"


def _sanitize_identifier(name: str, fallback: str = "item") -> str:
    safe = _sanitize_name(name, fallback=fallback)
    return safe.replace(".", "_").replace("-", "_")


def _unique_name(base_name: str, used: Set[str]) -> str:
    candidate = base_name
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{base_name}_{suffix}"
    used.add(candidate)
    return candidate


def _write_binary_stl(mesh: bpy.types.Mesh, filepath: str):
    """Write mesh as binary STL."""
    mesh.calc_loop_triangles()
    tris = mesh.loop_triangles
    if len(tris) == 0:
        raise ValueError("Mesh has no triangles")

    header = b"xarm_collision_export_stl"
    header = header + (b" " * (80 - len(header)))

    with open(filepath, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", len(tris)))
        verts = mesh.vertices
        for tri in tris:
            normal = tri.normal
            f.write(struct.pack("<3f", float(normal.x), float(normal.y), float(normal.z)))
            for vidx in tri.vertices:
                v = verts[vidx].co
                f.write(struct.pack("<3f", float(v.x), float(v.y), float(v.z)))
            f.write(struct.pack("<H", 0))


def _export_object_stl(obj: bpy.types.Object, filepath: str, depsgraph: bpy.types.Depsgraph):
    """Export evaluated object mesh data to STL."""
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        _write_binary_stl(mesh, filepath)
    finally:
        obj_eval.to_mesh_clear()


def _mesh_objects_from_collection(collection: bpy.types.Collection) -> List[bpy.types.Object]:
    """Return deterministic list of mesh objects from collection and nested children."""
    meshes = [obj for obj in collection.all_objects if obj.type == 'MESH']
    return sorted(meshes, key=lambda o: o.name.lower())


def _object_origin_xyz_rpy(obj: bpy.types.Object) -> Tuple[str, str]:
    """Convert world transform to URDF origin strings."""
    loc = obj.matrix_world.to_translation()
    rot = obj.matrix_world.to_euler('XYZ')
    xyz = _format_xyz((float(loc.x), float(loc.y), float(loc.z)))
    rpy = _format_xyz((float(rot.x), float(rot.y), float(rot.z)))
    return xyz, rpy


def _is_box_like_object(obj: bpy.types.Object, depsgraph: bpy.types.Depsgraph) -> bool:
    """Heuristic: object is a box primitive if evaluated mesh has 8 verts / 6 faces."""
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        return len(mesh.vertices) == 8 and len(mesh.polygons) == 6
    finally:
        obj_eval.to_mesh_clear()


def _object_box_size_xyz(obj: bpy.types.Object) -> str:
    dims = obj.dimensions
    # Clamp tiny/flat dimensions so collision boxes remain valid across simulators.
    min_dim = 0.01
    sx = max(min_dim, abs(float(dims.x)))
    sy = max(min_dim, abs(float(dims.y)))
    sz = max(min_dim, abs(float(dims.z)))
    return _format_xyz((sx, sy, sz))


def _append_geometry_node(geom_elem: ET.Element, kind: str, path: str, box_size: str):
    if kind == "box":
        ET.SubElement(geom_elem, "box", {"size": box_size})
    else:
        ET.SubElement(geom_elem, "mesh", {"filename": path, "scale": "1 1 1"})


def _append_default_inertial(
    link_elem: ET.Element,
    mass: str = "1.00000",
    inertia_diag: str = "1.00000",
):
    """Append a minimal inertial block to avoid simulator fallback defaults."""
    inertial = ET.SubElement(link_elem, "inertial")
    ET.SubElement(inertial, "origin", {"rpy": "0.00000 0.00000 0.00000", "xyz": "0.00000 0.00000 0.00000"})
    ET.SubElement(inertial, "mass", {"value": mass})
    ET.SubElement(inertial, "inertia", {
        "ixx": inertia_diag, "ixy": "0.00000", "ixz": "0.00000",
        "iyy": inertia_diag, "iyz": "0.00000", "izz": inertia_diag,
    })


def _append_link_geometry(link_elem: ET.Element, entries: List[Dict[str, Any]]):
    """Append visual/collision blocks for each exported object entry."""
    for entry in entries:
        visual = ET.SubElement(link_elem, "visual", {"name": f"viz_{entry['name']}"})
        ET.SubElement(visual, "origin", {"rpy": entry["rpy"], "xyz": entry["xyz"]})
        visual_geom = ET.SubElement(visual, "geometry")
        _append_geometry_node(
            geom_elem=visual_geom,
            kind=entry["visual_kind"],
            path=entry.get("visual_rel", ""),
            box_size=entry.get("visual_box_size", ""),
        )
        ET.SubElement(visual, "material", {"name": "None"})

        collision = ET.SubElement(link_elem, "collision", {"name": f"{entry['name']}_collision"})
        ET.SubElement(collision, "origin", {"rpy": entry["rpy"], "xyz": entry["xyz"]})
        collision_geom = ET.SubElement(collision, "geometry")
        _append_geometry_node(
            geom_elem=collision_geom,
            kind=entry["collision_kind"],
            path=entry.get("collision_rel", ""),
            box_size=entry.get("collision_box_size", ""),
        )


def _build_main_collision_urdf(robot_name: str, entries: List[Dict[str, Any]]) -> ET.Element:
    robot = ET.Element("robot", {"name": robot_name, "version": "1.0"})
    link = ET.SubElement(robot, "link", {"name": COLLISION_FIXED_LINK_NAME})
    _append_default_inertial(link)
    _append_link_geometry(link, entries)
    _indent_xml(robot)
    return robot


def _build_floating_base_urdf(entries: List[Dict[str, Any]]) -> ET.Element:
    robot = ET.Element("robot", {"name": "floatingbase", "version": "1.0"})

    joints = [
        ("FreeFlyerX", "prismatic", "base_link", "FreeFlyerX_Link", "1.00000 0.00000 0.00000"),
        ("FreeFlyerY", "prismatic", "FreeFlyerX_Link", "FreeFlyerY_Link", "0.00000 1.00000 0.00000"),
        ("FreeFlyerZ", "prismatic", "FreeFlyerY_Link", "FreeFlyerZ_Link", "0.00000 0.00000 1.00000"),
        ("FreeFlyerRX", "revolute", "FreeFlyerZ_Link", "FreeFlyerRX_Link", "1.00000 0.00000 0.00000"),
        ("FreeFlyerRY", "revolute", "FreeFlyerRX_Link", "FreeFlyerRY_Link", "0.00000 1.00000 0.00000"),
        ("FreeFlyerRZ", "revolute", "FreeFlyerRY_Link", COLLISION_FIXED_LINK_NAME, "0.00000 0.00000 1.00000"),
    ]

    for name, joint_type, parent, child, axis in joints:
        joint = ET.SubElement(robot, "joint", {"name": name, "type": joint_type})
        ET.SubElement(joint, "limit", {
            "lower": "-1.57000",
            "upper": "1.57000",
            "effort": "0.00000",
            "velocity": "0.00000",
        })
        ET.SubElement(joint, "origin", {"rpy": "0.00000 0.00000 0.00000", "xyz": "0.00000 0.00000 0.00000"})
        ET.SubElement(joint, "parent", {"link": parent})
        ET.SubElement(joint, "child", {"link": child})
        ET.SubElement(joint, "axis", {"xyz": axis})

    base_link = ET.SubElement(robot, "link", {"name": "base_link"})
    _append_default_inertial(base_link, mass="0.00000", inertia_diag="0.00000")

    freeflyer_x_link = ET.SubElement(robot, "link", {"name": "FreeFlyerX_Link"})
    _append_default_inertial(freeflyer_x_link)
    freeflyer_y_link = ET.SubElement(robot, "link", {"name": "FreeFlyerY_Link"})
    _append_default_inertial(freeflyer_y_link)
    freeflyer_z_link = ET.SubElement(robot, "link", {"name": "FreeFlyerZ_Link"})
    _append_default_inertial(freeflyer_z_link)
    freeflyer_rx_link = ET.SubElement(robot, "link", {"name": "FreeFlyerRX_Link"})
    _append_default_inertial(freeflyer_rx_link)
    freeflyer_ry_link = ET.SubElement(robot, "link", {"name": "FreeFlyerRY_Link"})
    _append_default_inertial(freeflyer_ry_link)

    final_link = ET.SubElement(robot, "link", {"name": COLLISION_FIXED_LINK_NAME})
    _append_default_inertial(final_link)
    _append_link_geometry(final_link, entries)

    _indent_xml(robot)
    return robot


def _write_urdf_xml(root_elem: ET.Element, filepath: str):
    ET.ElementTree(root_elem).write(filepath, encoding="utf-8", xml_declaration=False)


class XARM_OT_SelectCollisionExportDir(bpy.types.Operator):
    """Select folder for collision URDF export."""
    bl_idname = "xarm.select_collision_export_dir"
    bl_label = "Select Collision Export Folder"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(
        name="Folder",
        description="Folder used as root for collision URDF export",
        subtype='DIR_PATH',
    )

    def invoke(self, context, event):
        scene = context.scene
        if scene.xarm_collision_export_dir:
            self.filepath = scene.xarm_collision_export_dir
        else:
            self.filepath = bpy.path.abspath("//")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        selected = bpy.path.abspath(self.filepath)
        if not selected:
            self.report({'ERROR'}, "No folder selected")
            return {'CANCELLED'}

        if os.path.isfile(selected):
            selected = os.path.dirname(selected)

        context.scene.xarm_collision_export_dir = selected
        self.report({'INFO'}, f"Collision export folder set: {selected}")
        return {'FINISHED'}


class XARM_OT_ExportCollisionURDF(bpy.types.Operator):
    """Export collision collection to URDF bundle with floating-base model."""
    bl_idname = "xarm.export_collision_urdf"
    bl_label = "Export Collision URDF"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        collection = scene.xarm_collision_collection or bpy.data.collections.get(COLLISION_DEFAULT_COLLECTION)
        if collection is None:
            self.report({'ERROR'}, "Select collision collection (default expected: 'collision')")
            return {'CANCELLED'}

        urdf_name = _sanitize_identifier(scene.xarm_collision_urdf_name.strip(), fallback="site_collision")
        if not urdf_name:
            self.report({'ERROR'}, "URDF name is empty")
            return {'CANCELLED'}

        export_root = scene.xarm_collision_export_dir.strip() if scene.xarm_collision_export_dir else bpy.path.abspath("//")
        export_root = bpy.path.abspath(export_root)
        if not export_root:
            self.report({'ERROR'}, "Select export folder")
            return {'CANCELLED'}

        mesh_objects = _mesh_objects_from_collection(collection)
        if not mesh_objects:
            self.report({'ERROR'}, f"No mesh objects found in collection '{collection.name}'")
            return {'CANCELLED'}

        bundle_dir = os.path.join(export_root, urdf_name)
        main_urdf_dir = os.path.join(bundle_dir, "urdf")
        floating_urdf_dir = os.path.join(bundle_dir, "submodels", "floating_base", "urdf")
        stl_mesh_dir = os.path.join(bundle_dir, "meshes", "stl")

        os.makedirs(main_urdf_dir, exist_ok=True)
        os.makedirs(floating_urdf_dir, exist_ok=True)
        os.makedirs(stl_mesh_dir, exist_ok=True)

        depsgraph = context.evaluated_depsgraph_get()
        used_names: Set[str] = set()
        used_entry_names: Set[str] = set()
        entries_main: List[Dict[str, Any]] = []
        entries_floating: List[Dict[str, Any]] = []

        try:
            for obj in mesh_objects:
                mesh_base = _unique_name(_sanitize_identifier(obj.name, fallback="mesh"), used_names)
                mesh_abs = os.path.join(stl_mesh_dir, f"{mesh_base}.stl")

                xyz, rpy = _object_origin_xyz_rpy(obj)
                is_box = _is_box_like_object(obj, depsgraph)
                collision_box_size = _object_box_size_xyz(obj)
                if is_box:
                    box_size = _object_box_size_xyz(obj)
                    visual_kind = "box"
                    collision_kind = "box"
                    visual_rel_main = ""
                    collision_rel_main = ""
                    visual_rel_float = ""
                    collision_rel_float = ""
                else:
                    _export_object_stl(obj, mesh_abs, depsgraph)
                    visual_kind = "mesh"
                    # Use box collisions for compatibility with strict URDF loaders.
                    collision_kind = "box"
                    box_size = ""
                    visual_rel_main = os.path.relpath(mesh_abs, start=main_urdf_dir).replace("\\", "/")
                    collision_rel_main = ""
                    visual_rel_float = os.path.relpath(mesh_abs, start=floating_urdf_dir).replace("\\", "/")
                    collision_rel_float = ""

                entry_name = _unique_name(
                    _sanitize_identifier(obj.name, fallback=mesh_base),
                    used_entry_names,
                )
                entries_main.append({
                    "name": entry_name,
                    "xyz": xyz,
                    "rpy": rpy,
                    "visual_kind": visual_kind,
                    "collision_kind": collision_kind,
                    "visual_box_size": box_size,
                    "collision_box_size": collision_box_size,
                    "visual_rel": visual_rel_main,
                    "collision_rel": collision_rel_main,
                })
                entries_floating.append({
                    "name": entry_name,
                    "xyz": xyz,
                    "rpy": rpy,
                    "visual_kind": visual_kind,
                    "collision_kind": collision_kind,
                    "visual_box_size": box_size,
                    "collision_box_size": collision_box_size,
                    "visual_rel": visual_rel_float,
                    "collision_rel": collision_rel_float,
                })
        except Exception as e:
            self.report({'ERROR'}, f"Collision mesh export failed: {e}")
            return {'CANCELLED'}

        main_urdf_path = os.path.join(main_urdf_dir, f"{urdf_name}.urdf")
        floating_urdf_path = os.path.join(floating_urdf_dir, "floatingbase.urdf")

        try:
            main_root = _build_main_collision_urdf(urdf_name, entries_main)
            floating_root = _build_floating_base_urdf(entries_floating)
            _write_urdf_xml(main_root, main_urdf_path)
            _write_urdf_xml(floating_root, floating_urdf_path)
        except Exception as e:
            self.report({'ERROR'}, f"URDF write failed: {e}")
            return {'CANCELLED'}

        scene.xarm_collision_last_export_path = main_urdf_path
        self.report({'INFO'}, f"Exported collision URDF bundle: {urdf_name} ({len(entries_main)} meshes)")
        print(f"[SUCCESS] Collision URDF exported: {main_urdf_path}")
        print(f"[INFO] Floating base URDF: {floating_urdf_path}")
        return {'FINISHED'}


class XARM_OT_ClearMarkers(bpy.types.Operator):
    """Clear xArm violation markers from timeline"""
    bl_idname = "xarm.clear_markers"
    bl_label = "Clear Markers"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = clear_xarm_markers(context)
        if count > 0:
            self.report({'INFO'}, f"Cleared {count} xArm markers")
        else:
            self.report({'INFO'}, "No xArm markers to clear")
        return {'FINISHED'}


class XARM_OT_DirectExport(bpy.types.Operator):
    """Export animation to CSV without baking"""
    bl_idname = "xarm.direct_export"
    bl_label = "Export CSV (No Bake)"
    bl_options = {'REGISTER'}

    # File path property (set by file dialog)
    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to save CSV file",
        subtype='FILE_PATH'
    )

    # Export settings
    fps: bpy.props.FloatProperty(
        name="FPS",
        description="Frames per second",
        default=30.0,
        min=1.0,
        max=250.0
    )

    max_speed_pct: bpy.props.FloatProperty(
        name="Max Speed %",
        description="Maximum speed percentage cap (safety limit)",
        default=50.0,
        min=1.0,
        max=100.0
    )

    start_frame: bpy.props.IntProperty(
        name="Start Frame",
        description="First frame to export (-1 = use scene start)",
        default=-1
    )

    end_frame: bpy.props.IntProperty(
        name="End Frame",
        description="Last frame to export (-1 = use scene end)",
        default=-1
    )

    @classmethod
    def poll(cls, context):
        """Only available if rig armature found in collection"""
        arm = get_armature_from_collection(context.scene.xarm_active_collection)
        return arm is not None

    def invoke(self, context, event):
        """Open file dialog"""
        # Pre-fill filepath with default name
        armature = get_armature_from_collection(context.scene.xarm_active_collection)
        if armature:
            default_name = f"{armature.name}_export.csv"
            self.filepath = bpy.path.abspath(f"//{default_name}")

        # Pre-fill FPS from scene
        self.fps = context.scene.render.fps

        # Pre-fill frame range from scene
        if self.start_frame == -1:
            self.start_frame = context.scene.frame_start
        if self.end_frame == -1:
            self.end_frame = context.scene.frame_end

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        """Draw file dialog options"""
        layout = self.layout

        # Export settings
        box = layout.box()
        box.label(text="Export Settings", icon='SETTINGS')
        col = box.column(align=True)
        col.prop(self, "fps")
        col.prop(self, "max_speed_pct")
        row = col.row(align=True)
        row.prop(self, "start_frame")
        row.prop(self, "end_frame")

    def execute(self, context):
        """Export animation to CSV"""
        try:
            # Get armature from collection
            armature = get_armature_from_collection(context.scene.xarm_active_collection)
            if not armature:
                self.report({'ERROR'}, "No armature found in collection. Select a rig collection.")
                return {'CANCELLED'}

            # Ensure animation_data exists
            if not armature.animation_data:
                armature.animation_data_create()

            if not armature.animation_data.action:
                self.report({'ERROR'}, "No active action on armature")
                return {'CANCELLED'}

            # Get robot type from armature custom property
            robot_type = armature.get("xarm_robot_type", "uf850_twin")

            # Get robot config
            try:
                config = XArmRigConfig(robot_type)
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}

            # Determine frame range
            start_frame = self.start_frame if self.start_frame != -1 else context.scene.frame_start
            end_frame = self.end_frame if self.end_frame != -1 else context.scene.frame_end

            if start_frame > end_frame:
                self.report({'ERROR'}, f"Invalid frame range: {start_frame} to {end_frame}")
                return {'CANCELLED'}

            # Initialize extractors
            extractor = BoneAngleExtractor(armature.name, config)
            speed_calc = SpeedCalculator(
                max_velocity_deg_s=config.max_velocity_deg_s,
                fps=self.fps,
                max_speed_override=self.max_speed_pct
            )
            exporter = CSVExporter(self.filepath, include_tcp=False)

            # Export frames - collect violations by frame
            speed_frames: Dict[int, List] = {}  # frame -> [(joint_idx, velocity), ...]
            limit_frames: Dict[int, List] = {}  # frame -> [error_msg, ...]
            prev_angles = None
            max_speed_pct = 0.0  # Track peak speed

            # Get warning threshold from scene (default 90%)
            warning_threshold = context.scene.get('xarm_speed_warning_threshold', 90.0) / 100.0

            for frame in range(start_frame, end_frame + 1):
                # Get joint angles
                angles = extractor.get_joint_angles(frame)

                # Validate limits
                is_valid, errors = extractor.validate_limits(angles, frame)
                if not is_valid:
                    limit_frames[frame] = errors

                # Calculate speed
                if prev_angles is None:
                    speed_pct = 0.0
                    velocities = [0.0] * 6
                else:
                    speed_pct, velocities = speed_calc.calculate_speed(prev_angles, angles)

                    # Track max speed (uncapped)
                    actual_pct = (max(velocities) / config.max_velocity_deg_s) * 100.0
                    max_speed_pct = max(max_speed_pct, actual_pct)

                    # Check for speed violations (using scene threshold)
                    threshold_vel = config.max_velocity_deg_s * warning_threshold
                    violations = []
                    for j, vel in enumerate(velocities):
                        if vel > threshold_vel:
                            violations.append((j, vel))
                    if violations:
                        speed_frames[frame] = violations

                # Add frame to export
                time_s = (frame - start_frame) / self.fps
                exporter.add_frame(frame, time_s, angles, speed_pct)

                prev_angles = angles

            # Write CSV
            exporter.write()

            # Add markers to timeline
            num_frames = end_frame - start_frame + 1
            if speed_frames or limit_frames:
                add_violation_markers(context, speed_frames, limit_frames)

            # Prepare report data
            XARM_OT_ExportReport._report_data = {
                'filepath': os.path.basename(self.filepath),
                'num_frames': num_frames,
                'fps': self.fps,
                'max_speed_pct': max_speed_pct,
                'speed_frames': speed_frames,
                'limit_frames': limit_frames,
                'has_warnings': bool(speed_frames),
                'has_errors': bool(limit_frames),
            }

            # Report and show popup if issues found
            result_msg = f"Exported {num_frames} frames to {os.path.basename(self.filepath)}"

            if limit_frames:
                self.report({'WARNING'}, f"{result_msg} (with {len(limit_frames)} limit violations)")
                bpy.ops.xarm.export_report('INVOKE_DEFAULT')
            elif speed_frames:
                self.report({'WARNING'}, f"{result_msg} (with {len(speed_frames)} speed warnings)")
                bpy.ops.xarm.export_report('INVOKE_DEFAULT')
            else:
                # No issues - clear any existing markers
                cleared = clear_xarm_markers(context)
                if cleared > 0:
                    self.report({'INFO'}, f"{result_msg} (cleared {cleared} old markers)")
                else:
                    self.report({'INFO'}, result_msg)

            # Store last export path for playback
            context.scene.xarm_last_export_path = self.filepath

            print(f"\n[SUCCESS] CSV exported: {self.filepath}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {str(e)}")
            print(f"[ERROR] Export failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

class XARM_OT_BakeAndExport(bpy.types.Operator):
    """Bake animation then export to CSV"""
    bl_idname = "xarm.bake_and_export"
    bl_label = "Bake & Export CSV"
    bl_options = {'REGISTER'}

    # File path property (set by file dialog)
    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to save CSV file",
        subtype='FILE_PATH'
    )

    # Export settings
    fps: bpy.props.FloatProperty(
        name="FPS",
        description="Frames per second",
        default=30.0,
        min=1.0,
        max=250.0
    )

    max_speed_pct: bpy.props.FloatProperty(
        name="Max Speed %",
        description="Maximum speed percentage cap (safety limit)",
        default=50.0,
        min=1.0,
        max=100.0
    )

    start_frame: bpy.props.IntProperty(
        name="Start Frame",
        description="First frame to export (-1 = use scene start)",
        default=-1
    )

    end_frame: bpy.props.IntProperty(
        name="End Frame",
        description="Last frame to export (-1 = use scene end)",
        default=-1
    )

    @classmethod
    def poll(cls, context):
        """Only available if rig armature found in collection"""
        arm = get_armature_from_collection(context.scene.xarm_active_collection)
        return arm is not None

    def invoke(self, context, event):
        """Open file dialog"""
        # Pre-fill filepath with default name
        armature = get_armature_from_collection(context.scene.xarm_active_collection)
        if armature:
            default_name = f"{armature.name}_baked.csv"
            self.filepath = bpy.path.abspath(f"//{default_name}")

        # Pre-fill FPS from scene
        self.fps = context.scene.render.fps

        # Pre-fill frame range from scene
        if self.start_frame == -1:
            self.start_frame = context.scene.frame_start
        if self.end_frame == -1:
            self.end_frame = context.scene.frame_end

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        """Draw file dialog options"""
        layout = self.layout

        # Export settings
        box = layout.box()
        box.label(text="Export Settings", icon='SETTINGS')
        col = box.column(align=True)
        col.prop(self, "fps")
        col.prop(self, "max_speed_pct")
        row = col.row(align=True)
        row.prop(self, "start_frame")
        row.prop(self, "end_frame")

    def execute(self, context):
        """Bake animation and export to CSV"""
        baked_armature = None
        baked_action = None
        original_active_object = None
        try:
            # Get armature from collection
            armature = get_armature_from_collection(context.scene.xarm_active_collection)
            if not armature:
                self.report({'ERROR'}, "No armature found in collection. Select a rig collection.")
                return {'CANCELLED'}

            # Ensure animation_data exists
            if not armature.animation_data:
                armature.animation_data_create()

            # Store active object
            original_active_object = context.view_layer.objects.active

            if not armature.animation_data.action:
                self.report({'ERROR'}, "No active action on armature")
                return {'CANCELLED'}

            # Get robot type from armature custom property
            robot_type = armature.get("xarm_robot_type", "uf850_twin")

            # Get robot config
            try:
                config = XArmRigConfig(robot_type)
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}

            # Determine frame range
            start_frame = self.start_frame if self.start_frame != -1 else context.scene.frame_start
            end_frame = self.end_frame if self.end_frame != -1 else context.scene.frame_end

            if start_frame > end_frame:
                self.report({'ERROR'}, f"Invalid frame range: {start_frame} to {end_frame}")
                return {'CANCELLED'}

            # ── Bake Process ──────────────────────────
            print(f"[INFO] Baking animation for {armature.name}...")

            # 1. Duplicate armature
            baked_armature = armature.copy()
            baked_armature.data = armature.data.copy()
            baked_armature.name = f"{armature.name}_BAKE_TEMP"
            baked_armature.data.name = f"{armature.data.name}_BAKE_TEMP"
            context.collection.objects.link(baked_armature)

            # 2. Setup animation_data on baked armature
            # Link the same action - nla.bake with use_current_action=False will create new action
            if not baked_armature.animation_data:
                baked_armature.animation_data_create()
            baked_armature.animation_data.action = armature.animation_data.action

            # 3. Select and make active
            for obj in context.view_layer.objects:
                obj.select_set(False)
            baked_armature.select_set(True)
            context.view_layer.objects.active = baked_armature

            # 4. Bake with visual keying (converts constraints to keyframes)
            area_3d = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
            if area_3d is None:
                raise RuntimeError("No 3D Viewport visible. Open one and retry.")
            region = next((r for r in area_3d.regions if r.type == 'WINDOW'), None)

            with context.temp_override(area=area_3d, region=region):
                bpy.ops.object.mode_set(mode='POSE')
                bpy.ops.pose.select_all(action='SELECT')
                bpy.ops.nla.bake(
                    frame_start=start_frame,
                    frame_end=end_frame,
                    only_selected=False,
                    visual_keying=True,  # Critical: converts constraints to keyframes
                    clear_constraints=True,
                    clear_parents=False,
                    use_current_action=False,  # Creates NEW action, original untouched
                    bake_types={'POSE'}
                )
                bpy.ops.object.mode_set(mode='OBJECT')

            # Track the newly created baked action (for cleanup)
            baked_action = baked_armature.animation_data.action
            print(f"[INFO] Baking complete: {baked_armature.name} -> {baked_action.name}")

            # ── Export Process ─────────────────────────
            print(f"[INFO] Exporting baked animation...")

            # Initialize extractors (use baked armature)
            extractor = BoneAngleExtractor(baked_armature.name, config)
            speed_calc = SpeedCalculator(
                max_velocity_deg_s=config.max_velocity_deg_s,
                fps=self.fps,
                max_speed_override=self.max_speed_pct
            )
            exporter = CSVExporter(self.filepath, include_tcp=False)

            # Export frames - collect violations by frame
            speed_frames: Dict[int, List] = {}  # frame -> [(joint_idx, velocity), ...]
            limit_frames: Dict[int, List] = {}  # frame -> [error_msg, ...]
            prev_angles = None
            max_speed_pct = 0.0  # Track peak speed

            # Get warning threshold from scene (default 90%)
            warning_threshold = context.scene.get('xarm_speed_warning_threshold', 90.0) / 100.0

            for frame in range(start_frame, end_frame + 1):
                # Get joint angles
                angles = extractor.get_joint_angles(frame)

                # Validate limits
                is_valid, errors = extractor.validate_limits(angles, frame)
                if not is_valid:
                    limit_frames[frame] = errors

                # Calculate speed
                if prev_angles is None:
                    speed_pct = 0.0
                    velocities = [0.0] * 6
                else:
                    speed_pct, velocities = speed_calc.calculate_speed(prev_angles, angles)

                    # Track max speed (uncapped)
                    actual_pct = (max(velocities) / config.max_velocity_deg_s) * 100.0
                    max_speed_pct = max(max_speed_pct, actual_pct)

                    # Check for speed violations (using scene threshold)
                    threshold_vel = config.max_velocity_deg_s * warning_threshold
                    violations = []
                    for j, vel in enumerate(velocities):
                        if vel > threshold_vel:
                            violations.append((j, vel))
                    if violations:
                        speed_frames[frame] = violations

                # Add frame to export
                time_s = (frame - start_frame) / self.fps
                exporter.add_frame(frame, time_s, angles, speed_pct)

                prev_angles = angles

            # Write CSV
            exporter.write()

            # ── Cleanup ────────────────────────────────
            # Delete baked armature and action
            bpy.data.objects.remove(baked_armature, do_unlink=True)
            baked_armature = None
            bpy.data.actions.remove(baked_action)
            baked_action = None
            print(f"[INFO] Cleanup complete (temp armature and action removed)")

            # Add markers to timeline
            num_frames = end_frame - start_frame + 1
            if speed_frames or limit_frames:
                add_violation_markers(context, speed_frames, limit_frames)

            # Prepare report data
            XARM_OT_ExportReport._report_data = {
                'filepath': os.path.basename(self.filepath),
                'num_frames': num_frames,
                'fps': self.fps,
                'max_speed_pct': max_speed_pct,
                'speed_frames': speed_frames,
                'limit_frames': limit_frames,
                'has_warnings': bool(speed_frames),
                'has_errors': bool(limit_frames),
            }

            # Report and show popup if issues found
            result_msg = f"Baked and exported {num_frames} frames to {os.path.basename(self.filepath)}"

            if limit_frames:
                self.report({'WARNING'}, f"{result_msg} (with {len(limit_frames)} limit violations)")
                bpy.ops.xarm.export_report('INVOKE_DEFAULT')
            elif speed_frames:
                self.report({'WARNING'}, f"{result_msg} (with {len(speed_frames)} speed warnings)")
                bpy.ops.xarm.export_report('INVOKE_DEFAULT')
            else:
                # No issues - clear any existing markers
                cleared = clear_xarm_markers(context)
                if cleared > 0:
                    self.report({'INFO'}, f"{result_msg} (cleared {cleared} old markers)")
                else:
                    self.report({'INFO'}, result_msg)

            # Store last export path for playback
            context.scene.xarm_last_export_path = self.filepath

            print(f"\n[SUCCESS] Baked CSV exported: {self.filepath}")
            return {'FINISHED'}

        except Exception as e:
            # Cleanup on error
            if baked_armature and baked_armature.name in bpy.data.objects:
                try:
                    bpy.data.objects.remove(baked_armature, do_unlink=True)
                    print("[INFO] Cleaned up baked armature after error")
                except:
                    pass
            if baked_action and baked_action.name in bpy.data.actions:
                try:
                    bpy.data.actions.remove(baked_action)
                    print("[INFO] Cleaned up baked action after error")
                except:
                    pass

            self.report({'ERROR'}, f"Bake & Export failed: {str(e)}")
            print(f"[ERROR] Bake & Export failed: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}

        finally:
            # Restore original active object
            if original_active_object and original_active_object.name in bpy.data.objects:
                context.view_layer.objects.active = original_active_object


class XARM_OT_ExportSceneBundle(bpy.types.Operator):
    """Export a scene bundle with metadata JSON and one CSV per robot."""
    bl_idname = "xarm.export_scene_bundle"
    bl_label = "Export Scene Bundle"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        return len(scene.xarm_scene_export_slots) > 0

    def execute(self, context):
        scene = context.scene
        slots = scene.xarm_scene_export_slots

        if not slots:
            self.report({'ERROR'}, "Add at least one robot slot for scene export")
            return {'CANCELLED'}

        scene_name = scene.xarm_scene_export_name.strip() or scene.name
        root_dir = scene.xarm_scene_export_dir.strip() if scene.xarm_scene_export_dir else bpy.path.abspath("//")
        root_dir = bpy.path.abspath(root_dir)
        bundle_dir = os.path.join(root_dir, _sanitize_name(scene_name, fallback=_sanitize_name(scene.name)))
        csv_dir = os.path.join(bundle_dir, "csv")

        try:
            os.makedirs(csv_dir, exist_ok=True)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create export folder: {e}")
            return {'CANCELLED'}

        start_frame = scene.frame_start
        end_frame = scene.frame_end
        if start_frame > end_frame:
            self.report({'ERROR'}, f"Invalid frame range: {start_frame} to {end_frame}")
            return {'CANCELLED'}

        fps = float(scene.render.fps)
        max_speed_pct = 50.0
        warning_threshold = scene.xarm_speed_warning_threshold / 100.0

        used_file_names: Set[str] = set()
        metadata_robots: List[Dict[str, Any]] = []
        skipped: List[str] = []
        first_csv_export_path: Optional[str] = None

        for index, slot in enumerate(slots, start=1):
            robot_id = slot.robot_id.strip() or f"robot{index}"
            safe_robot = _sanitize_name(robot_id, fallback=f"robot{index}")
            collection = slot.collection

            if not collection:
                skipped.append(f"{robot_id}: no collection selected")
                continue

            armature = get_armature_from_collection(collection)
            if armature is None:
                skipped.append(f"{robot_id}: no xArm rig armature in collection '{collection.name}'")
                continue

            if not armature.animation_data or not armature.animation_data.action:
                skipped.append(f"{robot_id}: armature '{armature.name}' has no active action")
                continue

            base_name = safe_robot
            suffix = 1
            while base_name in used_file_names:
                suffix += 1
                base_name = f"{safe_robot}_{suffix}"
            used_file_names.add(base_name)

            csv_filename = f"{base_name}.csv"
            csv_path = os.path.join(csv_dir, csv_filename)
            if first_csv_export_path is None:
                first_csv_export_path = csv_path

            try:
                export_summary = _bake_armature_action_to_csv(
                    context=context,
                    armature=armature,
                    filepath=csv_path,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    fps=fps,
                    max_speed_pct=max_speed_pct,
                    warning_threshold=warning_threshold,
                )
            except Exception as e:
                skipped.append(f"{robot_id}: export failed ({e})")
                continue

            root_obj = _find_robot_root_object(collection, armature)
            translate, rotate_xyz = _get_transform_xyz(root_obj)
            rel_csv_path = os.path.join("csv", csv_filename).replace("\\", "/")

            metadata_robots.append({
                "id": robot_id,
                "collection": collection.name,
                "armature": armature.name,
                "transform": {
                    "rotateXYZ": rotate_xyz,
                    "translate": translate,
                },
                "animation": {
                    "path": rel_csv_path,
                    "length_frames": export_summary["num_frames"],
                    "fps": fps,
                    "action": export_summary["action_name"],
                },
                "validation": {
                    "speed_warning_frames": len(export_summary["speed_frames"]),
                    "joint_limit_violation_frames": len(export_summary["limit_frames"]),
                    "peak_speed_percent": round(float(export_summary["max_speed_pct"]), 3),
                },
            })

        if not metadata_robots:
            self.report({'ERROR'}, "Scene export failed: no robot slots were exported")
            return {'CANCELLED'}

        metadata = {
            "scene_name": scene_name,
            "export_source": "blender",
            "exported_at": datetime.now().isoformat(timespec='seconds'),
            "output_folder": bundle_dir,
            "frame_range": {
                "start": start_frame,
                "end": end_frame,
                "length_frames": (end_frame - start_frame + 1),
            },
            "fps": fps,
            "robots": metadata_robots,
        }
        if skipped:
            metadata["skipped"] = skipped

        metadata_path = os.path.join(bundle_dir, "scene_metadata.json")
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write metadata JSON: {e}")
            return {'CANCELLED'}

        if first_csv_export_path:
            context.scene.xarm_last_export_path = first_csv_export_path

        if skipped:
            self.report({'WARNING'}, f"Scene bundle exported ({len(metadata_robots)} robots, {len(skipped)} skipped)")
        else:
            self.report({'INFO'}, f"Scene bundle exported ({len(metadata_robots)} robots)")

        print(f"[SUCCESS] Scene bundle exported: {bundle_dir}")
        print(f"[INFO] Metadata: {metadata_path}")
        return {'FINISHED'}
