"""
Export Operators

Provides operators for exporting animations to CSV format.
- DirectExport: Export current animation without baking
- BakeAndExport: Bake animation first, then export
"""

import bpy
import os
from typing import Tuple, List, Dict, Set

from ..core.robot_config import XArmRigConfig
from ..core.bone_utils import BoneAngleExtractor
from ..core.csv_export import SpeedCalculator, CSVExporter


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

        # Speed violations
        speed_frames = data.get('speed_frames', {})
        if speed_frames:
            box = layout.box()
            box.label(text=f"Speed Violations ({len(speed_frames)} frames)", icon='SORTTIME')

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

    # Action selection
    action_name: bpy.props.StringProperty(
        name="Action",
        description="Action to export (leave empty for active action)",
        default=""
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
        """Only available if rig armature is set"""
        return context.scene.xarm_active_rig is not None

    def invoke(self, context, event):
        """Open file dialog"""
        # Pre-fill filepath with default name
        armature = context.scene.xarm_active_rig
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

        # Set action_name to active action if available
        if armature and armature.animation_data and armature.animation_data.action:
            self.action_name = armature.animation_data.action.name

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        """Draw file dialog options"""
        layout = self.layout

        # Action selection dropdown
        armature = context.scene.xarm_active_rig
        if armature:
            box = layout.box()
            box.label(text="Animation Action", icon='ACTION')

            # Get all actions
            actions = [action for action in bpy.data.actions]

            if actions:
                col = box.column(align=True)
                col.prop_search(self, "action_name", bpy.data, "actions", text="Action")
                col.label(text="(Leave empty for active action)", icon='INFO')
            else:
                box.label(text="No actions found", icon='ERROR')

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
        original_action = None
        try:
            # Get armature
            armature = context.scene.xarm_active_rig
            if not armature:
                self.report({'ERROR'}, "No armature set. Create rig first.")
                return {'CANCELLED'}

            # Ensure animation_data exists
            if not armature.animation_data:
                armature.animation_data_create()

            # Store original action
            original_action = armature.animation_data.action

            # Set action to export if specified
            if self.action_name:
                action = bpy.data.actions.get(self.action_name)
                if action:
                    armature.animation_data.action = action
                    print(f"[INFO] Exporting action: {self.action_name}")
                else:
                    self.report({'WARNING'}, f"Action '{self.action_name}' not found, using active action")
            elif not armature.animation_data.action:
                self.report({'ERROR'}, "No action selected and no active action on armature")
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

                    # Check for speed violations (>80% of max)
                    threshold_vel = config.max_velocity_deg_s * 0.8
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

        finally:
            # Restore original action
            if original_action is not None and armature and armature.animation_data:
                armature.animation_data.action = original_action
                print(f"[INFO] Restored original action")


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

    # Action selection
    action_name: bpy.props.StringProperty(
        name="Action",
        description="Action to export (leave empty for active action)",
        default=""
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
        """Only available if rig armature is set"""
        return context.scene.xarm_active_rig is not None

    def invoke(self, context, event):
        """Open file dialog"""
        # Pre-fill filepath with default name
        armature = context.scene.xarm_active_rig
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

        # Set action_name to active action if available
        if armature and armature.animation_data and armature.animation_data.action:
            self.action_name = armature.animation_data.action.name

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        """Draw file dialog options"""
        layout = self.layout

        # Action selection dropdown
        armature = context.scene.xarm_active_rig
        if armature:
            box = layout.box()
            box.label(text="Animation Action", icon='ACTION')

            # Get all actions
            actions = [action for action in bpy.data.actions]

            if actions:
                col = box.column(align=True)
                col.prop_search(self, "action_name", bpy.data, "actions", text="Action")
                col.label(text="(Leave empty for active action)", icon='INFO')
            else:
                box.label(text="No actions found", icon='ERROR')

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
        original_action = None
        original_active_object = None
        try:
            # Get armature
            armature = context.scene.xarm_active_rig
            if not armature:
                self.report({'ERROR'}, "No armature set. Create rig first.")
                return {'CANCELLED'}

            # Ensure animation_data exists
            if not armature.animation_data:
                armature.animation_data_create()

            # Store original action and active object
            original_action = armature.animation_data.action
            original_active_object = context.view_layer.objects.active

            # Set action to export if specified
            if self.action_name:
                action = bpy.data.actions.get(self.action_name)
                if action:
                    armature.animation_data.action = action
                    print(f"[INFO] Baking action: {self.action_name}")
                else:
                    self.report({'WARNING'}, f"Action '{self.action_name}' not found, using active action")
            elif not armature.animation_data.action:
                self.report({'ERROR'}, "No action selected and no active action on armature")
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

                    # Check for speed violations (>80% of max)
                    threshold_vel = config.max_velocity_deg_s * 0.8
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
            # Restore original action
            if original_action is not None and armature and armature.animation_data:
                armature.animation_data.action = original_action
                print(f"[INFO] Restored original action on source armature")

            # Restore original active object
            if original_active_object and original_active_object.name in bpy.data.objects:
                context.view_layer.objects.active = original_active_object
