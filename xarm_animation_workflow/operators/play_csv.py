"""
Play CSV Operator

Provides operators for playing exported CSV animations on xArm robot.
- SelectCSV: Choose CSV file to play
- PlayCSV: Execute playback using panel settings
- StopPlayback: Emergency stop
"""

import bpy
import os
import threading
from typing import Optional

from ..core.csv_playback import CSVPlayback


# Global playback state (for modal operator)
_playback_state = {
    'running': False,
    'progress': 0,
    'total': 0,
    'message': '',
    'error': None,
    'complete': False,
    'playback': None,
    'thread': None,
}


def _reset_playback_state():
    """Reset global playback state."""
    _playback_state['running'] = False
    _playback_state['progress'] = 0
    _playback_state['total'] = 0
    _playback_state['message'] = ''
    _playback_state['error'] = None
    _playback_state['complete'] = False
    _playback_state['playback'] = None
    _playback_state['thread'] = None


class XARM_OT_SelectCSV(bpy.types.Operator):
    """Select CSV file for robot playback"""
    bl_idname = "xarm.select_csv"
    bl_label = "Select CSV File"
    bl_options = {'REGISTER'}

    # File path
    filepath: bpy.props.StringProperty(
        name="CSV File",
        description="Path to animation CSV file",
        subtype='FILE_PATH'
    )

    # Filter for file browser
    filter_glob: bpy.props.StringProperty(
        default="*.csv",
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        """Open file dialog."""
        scene = context.scene

        # Pre-fill with last export or current selection
        if scene.xarm_playback_csv_path:
            self.filepath = scene.xarm_playback_csv_path
        elif scene.xarm_last_export_path:
            self.filepath = scene.xarm_last_export_path

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        """Store selected file path."""
        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"File not found: {self.filepath}")
            return {'CANCELLED'}

        if not self.filepath.endswith('.csv'):
            self.report({'ERROR'}, "File must be a CSV file")
            return {'CANCELLED'}

        # Store in scene property
        context.scene.xarm_playback_csv_path = self.filepath
        self.report({'INFO'}, f"Selected: {os.path.basename(self.filepath)}")
        return {'FINISHED'}


class XARM_OT_PlayCSV(bpy.types.Operator):
    """Play selected CSV animation on xArm robot"""
    bl_idname = "xarm.play_csv"
    bl_label = "Play on Robot"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Only enable if CSV is selected and not already playing."""
        scene = context.scene
        has_csv = bool(scene.xarm_playback_csv_path)
        not_running = not _playback_state['running']
        return has_csv and not_running

    def execute(self, context):
        """Start playback using panel settings."""
        scene = context.scene

        # Get settings from scene properties
        filepath = scene.xarm_playback_csv_path
        robot_ip = scene.xarm_robot_ip
        mode = scene.xarm_playback_mode
        loops = scene.xarm_playback_loops

        # Validate file
        if not filepath or not os.path.exists(filepath):
            self.report({'ERROR'}, f"CSV file not found. Select a file first.")
            return {'CANCELLED'}

        # Check if already playing
        if _playback_state['running']:
            self.report({'ERROR'}, "Playback already in progress")
            return {'CANCELLED'}

        # Reset state
        _reset_playback_state()

        # Create playback instance
        try:
            playback = CSVPlayback(robot_ip)
            rows = playback.load_csv(filepath)
        except ImportError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load CSV: {e}")
            return {'CANCELLED'}

        # Store settings
        _playback_state['playback'] = playback
        _playback_state['total'] = len(rows) * loops

        # Progress callback
        def progress_callback(current, total, message):
            _playback_state['progress'] = current
            _playback_state['total'] = total
            _playback_state['message'] = message

        playback.set_progress_callback(progress_callback)

        # Playback function for thread
        def run_playback():
            _playback_state['running'] = True
            try:
                # Connect
                _playback_state['message'] = "Connecting to robot..."
                if not playback.connect():
                    _playback_state['error'] = "Failed to connect to robot"
                    return

                # Play
                if mode == 'cued':
                    success = playback.play_cued(rows, loops, move_to_first=True)
                else:
                    success = playback.play_servo(rows, loops, move_to_first=True)

                if not success and not _playback_state['error']:
                    _playback_state['error'] = "Playback failed or was stopped"

            except Exception as e:
                _playback_state['error'] = str(e)
            finally:
                playback.disconnect()
                _playback_state['running'] = False
                _playback_state['complete'] = True

        # Start thread
        thread = threading.Thread(target=run_playback, daemon=True)
        _playback_state['thread'] = thread
        thread.start()

        # Start modal timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)

        self.report({'INFO'}, f"Starting playback: {os.path.basename(filepath)}")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        """Handle modal updates."""
        if event.type == 'TIMER':
            # Check if complete
            if _playback_state['complete']:
                context.window_manager.event_timer_remove(self._timer)

                if _playback_state['error']:
                    self.report({'ERROR'}, _playback_state['error'])
                    _reset_playback_state()
                    return {'CANCELLED'}
                else:
                    self.report({'INFO'}, "Playback complete")
                    _reset_playback_state()
                    return {'FINISHED'}

            # Redraw for progress
            context.area.tag_redraw()

        elif event.type == 'ESC':
            # Stop playback
            if _playback_state['playback']:
                _playback_state['playback'].stop()
            self.report({'WARNING'}, "Playback stopped by user")
            context.window_manager.event_timer_remove(self._timer)
            _reset_playback_state()
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def cancel(self, context):
        """Handle cancellation."""
        if hasattr(self, '_timer'):
            context.window_manager.event_timer_remove(self._timer)
        if _playback_state['playback']:
            _playback_state['playback'].stop()
        _reset_playback_state()


class XARM_OT_StopPlayback(bpy.types.Operator):
    """Stop robot playback"""
    bl_idname = "xarm.stop_playback"
    bl_label = "Stop Playback"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if _playback_state['playback']:
            _playback_state['playback'].stop()
            self.report({'WARNING'}, "Stopping playback...")
        else:
            self.report({'INFO'}, "No playback in progress")
        return {'FINISHED'}


def get_playback_status() -> dict:
    """Get current playback status for UI display."""
    return {
        'running': _playback_state['running'],
        'progress': _playback_state['progress'],
        'total': _playback_state['total'],
        'message': _playback_state['message'],
    }
