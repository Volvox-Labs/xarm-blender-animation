"""
Real-time Animation Streaming Test Script

Streams Blender animation to xArm robot in real-time.

Modes:
- JOINT: Stream joint angles via set_servo_angle_j (servo mode)
         Works for FK and IK modes
         Reads evaluated bone transforms (includes IK solving)
- TCP:   Send TCP position via set_position (PTP mode)
         Uses robot's internal IK
         Reads tcp bone world position

Usage:
1. Run script in Blender's Text Editor
2. Open N-sidebar > 'Stream Test' tab
3. Configure: Armature, Robot IP, Stream Mode
4. Click 'Start Interactive' or 'Start Timeline'
5. Move bones or play animation - robot follows
6. Click 'Stop Stream' when done
"""

import bpy
import math
import time
from typing import Dict, List, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_ROBOT_IP = "localhost"
DEFAULT_TCP_BONE = "tcp"
DEFAULT_JOINT_SPEED = 180    # deg/s for joint streaming
DEFAULT_TCP_SPEED = 100      # mm/s for TCP movement

# Scale: Blender units to mm
ROBOT_SCALE = 1000.0

# TCP mode change thresholds (only send if position/rotation changed)
TCP_POS_THRESHOLD = 1.0    # mm - minimum position change to trigger send
TCP_ROT_THRESHOLD = 0.5    # deg - minimum rotation change to trigger send


# ═══════════════════════════════════════════════════════════════════════════════
# Robot Configuration
# ═══════════════════════════════════════════════════════════════════════════════

ROBOT_CONFIGS = {
    'uf850_twin': {
        'bone_names': ['joint_1', 'joint_2', 'joint_3', 'joint_4', 'joint_5', 'joint_6'],
        'rotation_axes': ['Y', 'Z', '-Z', 'Y', 'Z', 'Y'],
        'joint_limits_deg': [
            (-360, 360),     # J1
            (-131.9, 131.9), # J2
            (-241.9, 3.4),   # J3
            (-360, 360),     # J4
            (-123.9, 123.9), # J5
            (-360, 360),     # J6
        ],
    },
    'ufxarm6_twin': {
        'bone_names': ['joint_1', 'joint_2', 'joint_3', 'joint_4', 'joint_5', 'joint_6'],
        'rotation_axes': ['Y', '-Z', '-Z', 'Y', '-Z', 'Y'],
        'joint_limits_deg': [
            (-360, 360),
            (-131.9, 131.9),
            (-241.9, 3.4),
            (-360, 360),
            (-123.9, 123.9),
            (-360, 360),
        ],
    }
}


# ═══════════════════════════════════════════════════════════════════════════════
# Global State
# ═══════════════════════════════════════════════════════════════════════════════

_stream_state = {
    'active': False,
    'timeline_mode': False,  # True = timeline playback, False = interactive
    'arm': None,
    'armature_name': None,  # Store name, not reference (avoids stale reference errors)
    'config': None,
    'stream_mode': 'JOINT',  # Current stream mode
    'tcp_bone_name': 'tcp',
    'joint_speed': DEFAULT_JOINT_SPEED,
    'tcp_speed': DEFAULT_TCP_SPEED,
    'last_angles': None,
    'last_tcp_pos': None,    # Last sent TCP position (x,y,z,roll,pitch,yaw)
    'last_send_time': 0,
    'last_frame': -1,
    'error_count': 0,
    'last_err_code': 0,
    'last_warn_code': 0,
    'last_state': None,
    'last_mode': None,
    'last_sdk_ok': False,
}

# Minimum time between sends (seconds) - prevents flooding robot
MIN_SEND_INTERVAL = 0.033  # ~30 Hz


# ═══════════════════════════════════════════════════════════════════════════════
# Core Functions
# ═══════════════════════════════════════════════════════════════════════════════

def clamp_to_limits(angles: List[float], limits: List[tuple]) -> List[float]:
    """Clamp joint angles to limits."""
    return [max(lo, min(hi, a)) for a, (lo, hi) in zip(angles, limits)]


def get_joint_angles(armature_obj, depsgraph, config: dict) -> List[float]:
    """
    Get joint angles from evaluated bone matrices (works with FK and IK).

    Reads the final bone transforms after IK constraints are applied,
    then extracts the rotation relative to the rest pose.
    """
    try:
        # Get evaluated armature (with IK solved)
        armature_eval = armature_obj.evaluated_get(depsgraph)

        joint_angles = []

        for i, (bone_name, axis) in enumerate(zip(config['bone_names'], config['rotation_axes'])):
            pose_bone = armature_eval.pose.bones.get(bone_name)
            if pose_bone is None:
                print(f"[WARN] Bone '{bone_name}' not found")
                joint_angles.append(0.0)
                continue

            # Get rest bone data
            rest_bone = armature_eval.data.bones.get(bone_name)
            if rest_bone is None:
                joint_angles.append(0.0)
                continue

            # Get matrices
            pose_matrix = pose_bone.matrix
            rest_matrix = rest_bone.matrix_local

            # Compute local matrices relative to parent
            if pose_bone.parent and rest_bone.parent:
                parent_pose = pose_bone.parent.matrix
                parent_rest = rest_bone.parent.matrix_local

                # Local matrices
                local_pose = parent_pose.inverted() @ pose_matrix
                local_rest = parent_rest.inverted() @ rest_matrix
            else:
                local_pose = pose_matrix
                local_rest = rest_matrix

            # Delta rotation: pose relative to rest
            delta = local_rest.inverted() @ local_pose

            # Extract euler rotation
            euler = delta.to_euler('XYZ')

            # Parse axis and sign
            if axis.startswith('-'):
                sign = -1
                axis_char = axis[1:]
            else:
                sign = 1
                axis_char = axis

            axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[axis_char]
            angle_deg = math.degrees(euler[axis_idx]) * sign

            # Clamp to limits
            min_lim, max_lim = config['joint_limits_deg'][i]
            angle_deg = max(min_lim, min(max_lim, angle_deg))

            joint_angles.append(angle_deg)

        return joint_angles

    except ReferenceError:
        # Armature reference is stale, return zeros
        return [0.0] * len(config['bone_names'])


def get_tcp_position(armature_obj, depsgraph, tcp_bone_name: str) -> Tuple[float, ...]:
    """
    Get TCP bone world position and orientation for xArm robot.

    Position: Direct mapping (Blender model matches robot coordinate system)
    - robot_x = blender_x
    - robot_y = blender_y
    - robot_z = blender_z

    Rotation: World rotation from bone's world matrix (absolute orientation)
    - xArm roll/pitch/yaw = TCP bone world euler X/Y/Z

    Returns: (x, y, z, roll, pitch, yaw) in mm and degrees
    """
    try:
        armature_eval = armature_obj.evaluated_get(depsgraph)
        pose_bone = armature_eval.pose.bones.get(tcp_bone_name)

        if pose_bone is None:
            print(f"[ERROR] TCP bone '{tcp_bone_name}' not found")
            return (0, 0, 0, 0, 0, 0)

        # Get world matrix (includes armature transform and bone pose)
        matrix_world = armature_eval.matrix_world @ pose_bone.matrix

        # Position: Direct mapping (no coordinate transform)
        location = matrix_world.translation
        robot_x = location.x * ROBOT_SCALE
        robot_y = location.y * ROBOT_SCALE
        robot_z = location.z * ROBOT_SCALE

        # Rotation: Transform from Blender TCP frame to Robot TCP frame
        # Blender TCP bone: Y down (tool), X left, Z forward
        # Robot TCP frame:  Z down (tool), X right, Y forward
        #
        # Tested mapping (verified against robot):
        #   roll  = euler_x + 90
        #   pitch = -(euler_z + 180)
        #   yaw   = euler_y
        #
        # At home: euler_ZYX=(90, 0, -180) -> robot=(180, 0, 0)
        euler_zyx = matrix_world.to_euler('ZYX')

        euler_x_deg = math.degrees(euler_zyx.x)
        euler_y_deg = math.degrees(euler_zyx.y)
        euler_z_deg = math.degrees(euler_zyx.z)

        robot_roll = euler_x_deg + 90
        robot_pitch = -(euler_z_deg + 180)
        robot_yaw = euler_y_deg

        # Normalize all angles to [-180, 180] range
        def normalize_angle(a):
            while a > 180:
                a -= 360
            while a < -180:
                a += 360
            return a

        robot_roll = normalize_angle(robot_roll)
        robot_pitch = normalize_angle(robot_pitch)
        robot_yaw = normalize_angle(robot_yaw)

        return (robot_x, robot_y, robot_z, robot_roll, robot_pitch, robot_yaw)

    except ReferenceError:
        # Armature reference is stale, return zeros
        return (0, 0, 0, 0, 0, 0)


def is_localhost(ip: str) -> bool:
    return ip in ('localhost', '127.0.0.1', '::1')


def _on_error_warn_changed(data):
    """Track latest err/warn values from SDK callback."""
    global _stream_state
    if not isinstance(data, dict):
        return
    if 'error_code' in data:
        _stream_state['last_err_code'] = int(data.get('error_code', 0) or 0)
    if 'warn_code' in data:
        _stream_state['last_warn_code'] = int(data.get('warn_code', 0) or 0)


def _on_state_changed(data):
    """Track latest state value from SDK callback."""
    global _stream_state
    if not isinstance(data, dict):
        return
    if 'state' in data:
        _stream_state['last_state'] = int(data.get('state', 0))


def _poll_robot_status(arm) -> Dict:
    """
    Robust robot status read:
    1) Validate transport connection
    2) Poll err/warn + state with explicit return-code checks
    3) Fall back to cached SDK properties/callbacks if polling fails
    """
    global _stream_state
    status = {
        'connected': False,
        'error': None,
        'warn': None,
        'state': None,
        'mode': None,
        'sdk_ok': False,
    }

    if arm is None or not getattr(arm, 'connected', False):
        return status

    status['connected'] = True
    err_code = int(getattr(arm, 'error_code', _stream_state.get('last_err_code', 0)) or 0)
    warn_code = int(getattr(arm, 'warn_code', _stream_state.get('last_warn_code', 0)) or 0)
    state = _stream_state.get('last_state', None)
    mode = _stream_state.get('last_mode', None)
    sdk_ok = True

    try:
        code, values = arm.get_err_warn_code()
        if code == 0 and isinstance(values, (list, tuple)) and len(values) >= 2:
            err_code = int(values[0])
            warn_code = int(values[1])
        else:
            sdk_ok = False
    except Exception:
        sdk_ok = False

    try:
        code, state_value = arm.get_state()
        if code == 0:
            state = int(state_value)
        else:
            sdk_ok = False
    except Exception:
        sdk_ok = False

    try:
        mode = int(getattr(arm, 'mode', mode))
    except Exception:
        pass

    _stream_state['last_err_code'] = int(err_code)
    _stream_state['last_warn_code'] = int(warn_code)
    _stream_state['last_state'] = state
    _stream_state['last_mode'] = mode
    _stream_state['last_sdk_ok'] = sdk_ok

    status.update({
        'error': int(err_code),
        'warn': int(warn_code),
        'state': state,
        'mode': mode,
        'sdk_ok': sdk_ok,
    })
    return status


def angles_changed(new_angles, old_angles, threshold=0.1) -> bool:
    """Check if angles changed significantly."""
    if old_angles is None:
        return True
    for new, old in zip(new_angles, old_angles):
        if abs(new - old) > threshold:
            return True
    return False


def tcp_changed(new_pos, old_pos) -> bool:
    """Check if TCP position/rotation changed significantly."""
    if old_pos is None:
        return True
    # Position check (first 3 values: x, y, z in mm)
    for i in range(3):
        if abs(new_pos[i] - old_pos[i]) > TCP_POS_THRESHOLD:
            return True
    # Rotation check (last 3 values: roll, pitch, yaw in degrees)
    for i in range(3, 6):
        if abs(new_pos[i] - old_pos[i]) > TCP_ROT_THRESHOLD:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Depsgraph Update Handler (for interactive bone movement)
# ═══════════════════════════════════════════════════════════════════════════════

def depsgraph_update_handler(scene, depsgraph):
    """
    Called when depsgraph updates - fires when bones are moved interactively.
    This is the key handler for real-time streaming during pose editing.
    """
    global _stream_state

    if not _stream_state['active']:
        return

    arm = _stream_state['arm']
    armature_name = _stream_state['armature_name']
    config = _stream_state['config']
    stream_mode = _stream_state['stream_mode']

    if arm is None or armature_name is None:
        return

    # Fetch armature by name each time (avoids stale reference errors after undo/reload)
    armature = bpy.data.objects.get(armature_name)
    if armature is None or armature.type != 'ARMATURE':
        return

    # Throttle: don't send too frequently
    current_time = time.time()
    if current_time - _stream_state['last_send_time'] < MIN_SEND_INTERVAL:
        return

    # Check if our armature was updated
    armature_updated = False
    for update in depsgraph.updates:
        if update.id.name == armature_name:
            armature_updated = True
            break

    if not armature_updated:
        return

    try:
        if stream_mode == "JOINT":
            # Get joint angles from evaluated bones (works with FK and IK)
            angles = get_joint_angles(armature, depsgraph, config)

            # Skip if no significant change
            if not angles_changed(angles, _stream_state['last_angles']):
                return
            _stream_state['last_angles'] = angles[:]
            _stream_state['last_send_time'] = current_time

            # Stream to robot via servo mode
            # Note: is_radian=False means angles are in degrees, speed in deg/s
            code = arm.set_servo_angle_j(
                angles,
                speed=_stream_state['joint_speed'],
                mvacc=1000,
                is_radian=False,
                wait=False
            )

            if code != 0:
                _stream_state['error_count'] += 1
                if _stream_state['error_count'] <= 5:
                    print(f"[ERROR] set_servo_angle_j: {code}")
            else:
                # Debug: print angles periodically
                print(f"[JOINT] {[f'{a:.1f}' for a in angles]}")

        else:  # TCP mode
            # Get TCP bone position
            tcp_bone = _stream_state['tcp_bone_name']
            pos = get_tcp_position(armature, depsgraph, tcp_bone)

            # Skip if no significant change (reduces robot commands)
            if not tcp_changed(pos, _stream_state['last_tcp_pos']):
                return
            _stream_state['last_tcp_pos'] = pos
            _stream_state['last_send_time'] = current_time

            x, y, z, roll, pitch, yaw = pos

            # Send to robot via PTP (is_radian=False for degrees)
            code = arm.set_position(
                x=x, y=y, z=z,
                roll=roll, pitch=pitch, yaw=yaw,
                speed=_stream_state['tcp_speed'],
                is_radian=False,
                wait=False
            )

            if code != 0:
                _stream_state['error_count'] += 1
                if _stream_state['error_count'] <= 5:
                    print(f"[ERROR] set_position: {code}")
            else:
                print(f"[TCP] pos=({x:.1f}, {y:.1f}, {z:.1f}) rot=({roll:.1f}, {pitch:.1f}, {yaw:.1f})")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# Timeline Playback Handler
# ═══════════════════════════════════════════════════════════════════════════════

def frame_change_handler(scene, depsgraph):
    """
    Called on timeline frame change - stream to robot during animation playback.
    """
    global _stream_state

    if not _stream_state['active'] or not _stream_state['timeline_mode']:
        return

    arm = _stream_state['arm']
    armature_name = _stream_state['armature_name']
    config = _stream_state['config']
    stream_mode = _stream_state['stream_mode']

    if arm is None or armature_name is None:
        return

    # Fetch armature by name
    armature = bpy.data.objects.get(armature_name)
    if armature is None or armature.type != 'ARMATURE':
        return

    # Skip if same frame (avoid duplicate sends)
    current_frame = scene.frame_current
    if current_frame == _stream_state['last_frame']:
        return
    _stream_state['last_frame'] = current_frame

    try:
        if stream_mode == "JOINT":
            angles = get_joint_angles(armature, depsgraph, config)
            _stream_state['last_angles'] = angles[:]

            code = arm.set_servo_angle_j(
                angles,
                speed=_stream_state['joint_speed'],
                mvacc=1000,
                is_radian=False,
                wait=False
            )

            if code != 0:
                _stream_state['error_count'] += 1
                if _stream_state['error_count'] <= 5:
                    print(f"[ERROR] set_servo_angle_j: {code}")
            else:
                if current_frame % 10 == 0:
                    print(f"[F{current_frame}] {[f'{a:.1f}' for a in angles]}")

        else:  # TCP mode
            tcp_bone = _stream_state['tcp_bone_name']
            pos = get_tcp_position(armature, depsgraph, tcp_bone)

            # Skip if no significant change
            if not tcp_changed(pos, _stream_state['last_tcp_pos']):
                return
            _stream_state['last_tcp_pos'] = pos

            x, y, z, roll, pitch, yaw = pos

            code = arm.set_position(
                x=x, y=y, z=z,
                roll=roll, pitch=pitch, yaw=yaw,
                speed=_stream_state['tcp_speed'],
                is_radian=False,
                wait=False
            )

            if code != 0:
                _stream_state['error_count'] += 1
                if _stream_state['error_count'] <= 5:
                    print(f"[ERROR] set_position: {code}")
            else:
                if current_frame % 10 == 0:
                    print(f"[F{current_frame}] TCP ({x:.1f}, {y:.1f}, {z:.1f}) R({roll:.1f}, {pitch:.1f}, {yaw:.1f})")

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# Start/Stop
# ═══════════════════════════════════════════════════════════════════════════════

def start_stream(context, timeline_mode=False):
    """Connect and start streaming.

    Args:
        context: Blender context
        timeline_mode: If True, stream during timeline playback.
                      If False, stream during interactive bone movement.
    """
    global _stream_state

    if _stream_state['active']:
        print("[INFO] Already streaming")
        return False

    scene = context.scene

    # Get settings from scene properties
    armature = scene.stream_armature
    robot_ip = scene.stream_robot_ip
    robot_type = scene.stream_robot_type
    stream_mode = scene.stream_mode
    tcp_bone = scene.stream_tcp_bone
    joint_speed = scene.stream_joint_speed
    tcp_speed = scene.stream_tcp_speed

    # Validate armature
    if armature is None or armature.type != 'ARMATURE':
        print("[ERROR] No armature selected")
        return False

    # Validate config
    if robot_type not in ROBOT_CONFIGS:
        print(f"[ERROR] Unknown robot type: {robot_type}")
        return False
    config = ROBOT_CONFIGS[robot_type]

    # Import xArm SDK
    try:
        from xarm.wrapper import XArmAPI
    except ImportError:
        print("[ERROR] xArm SDK not found - copy xarm folder to Blender's Python lib")
        return False

    # Connect
    print(f"[INFO] Connecting to {robot_ip}...")
    print(f"[INFO] Armature: {armature.name}")
    print(f"[INFO] Mode: {stream_mode}")

    try:
        sim = is_localhost(robot_ip)
        if sim:
            arm = XArmAPI(robot_ip, baud_checkset=False, check_joint_limit=False)
            print("[INFO] Simulation mode")
        else:
            arm = XArmAPI(robot_ip)
            print("[INFO] Real robot")

        # Initialize
        arm.clean_warn()
        arm.clean_error()
        arm.motion_enable(True)
        arm.set_mode(0)
        arm.set_state(0)
        time.sleep(0.5)

        # Get current position
        _, curr_angles = arm.get_servo_angle()
        print(f"[INFO] Current: {[f'{a:.1f}' for a in curr_angles]}")

        # Register status callbacks (best-effort, non-blocking).
        try:
            arm.register_error_warn_changed_callback(_on_error_warn_changed)
            arm.register_state_changed_callback(_on_state_changed)
        except Exception as e:
            print(f"[WARN] Failed to register status callbacks: {e}")

        # Set mode based on stream type
        if stream_mode == "JOINT":
            arm.set_mode(1)  # Servo mode for joint streaming
            arm.set_state(0)
            time.sleep(0.3)
            print("[INFO] Servo mode enabled (joint streaming)")
        else:
            print("[INFO] Position mode (TCP PTP)")

        startup_status = _poll_robot_status(arm)
        print(
            "[INFO] Status: "
            f"state={startup_status.get('state')} "
            f"mode={startup_status.get('mode')} "
            f"err={startup_status.get('error')} "
            f"warn={startup_status.get('warn')}"
        )

    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return False

    # Store state (use armature name, not reference, to avoid stale reference errors)
    _stream_state['active'] = True
    _stream_state['timeline_mode'] = timeline_mode
    _stream_state['arm'] = arm
    _stream_state['armature_name'] = armature.name
    _stream_state['config'] = config
    _stream_state['stream_mode'] = stream_mode
    _stream_state['tcp_bone_name'] = tcp_bone
    _stream_state['joint_speed'] = joint_speed
    _stream_state['tcp_speed'] = tcp_speed
    _stream_state['last_angles'] = None
    _stream_state['last_tcp_pos'] = None
    _stream_state['last_frame'] = -1
    _stream_state['error_count'] = 0
    _stream_state['last_err_code'] = int(getattr(arm, 'error_code', 0) or 0)
    _stream_state['last_warn_code'] = int(getattr(arm, 'warn_code', 0) or 0)
    _stream_state['last_state'] = startup_status.get('state')
    _stream_state['last_mode'] = startup_status.get('mode')
    _stream_state['last_sdk_ok'] = bool(startup_status.get('sdk_ok', False))

    # Register appropriate handler
    if timeline_mode:
        if frame_change_handler not in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.append(frame_change_handler)
        print("[INFO] Timeline streaming started - press Play to stream")
    else:
        if depsgraph_update_handler not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(depsgraph_update_handler)
        print("[INFO] Interactive streaming started - move bones to stream")
    return True


def stop_stream():
    """Stop streaming and disconnect."""
    global _stream_state

    # Remove both handlers (whichever is active)
    if depsgraph_update_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update_handler)
    if frame_change_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(frame_change_handler)

    arm = _stream_state['arm']
    if arm:
        try:
            arm.release_error_warn_changed_callback(_on_error_warn_changed)
        except Exception:
            pass
        try:
            arm.release_state_changed_callback(_on_state_changed)
        except Exception:
            pass
        try:
            arm.set_mode(0)
            arm.set_state(0)
            arm.disconnect()
        except:
            pass

    _stream_state['active'] = False
    _stream_state['timeline_mode'] = False
    _stream_state['arm'] = None
    _stream_state['armature_name'] = None
    _stream_state['config'] = None
    _stream_state['last_angles'] = None
    _stream_state['last_tcp_pos'] = None
    _stream_state['last_send_time'] = 0
    _stream_state['last_frame'] = -1
    _stream_state['error_count'] = 0
    _stream_state['last_err_code'] = 0
    _stream_state['last_warn_code'] = 0
    _stream_state['last_state'] = None
    _stream_state['last_mode'] = None
    _stream_state['last_sdk_ok'] = False

    print("[INFO] Streaming stopped")


def send_once(context):
    """Send current position once (for testing). Uses wait=False to not block Blender."""
    if not _stream_state['active']:
        print("[ERROR] Not connected")
        return

    arm = _stream_state['arm']
    armature_name = _stream_state['armature_name']
    config = _stream_state['config']
    stream_mode = _stream_state['stream_mode']

    # Fetch armature by name
    armature = bpy.data.objects.get(armature_name)
    if armature is None:
        print(f"[ERROR] Armature '{armature_name}' not found")
        return

    depsgraph = context.evaluated_depsgraph_get()

    if stream_mode == "JOINT":
        angles = get_joint_angles(armature, depsgraph, config)
        print(f"[SEND] Angles: {[f'{a:.1f}' for a in angles]}")
        code = arm.set_servo_angle(angle=angles, speed=30, is_radian=False, wait=False)
        print(f"[SEND] Result: {code}")
    else:
        tcp_bone = _stream_state['tcp_bone_name']
        pos = get_tcp_position(armature, depsgraph, tcp_bone)
        x, y, z, roll, pitch, yaw = pos
        print(f"[SEND] TCP: pos=({x:.1f}, {y:.1f}, {z:.1f}) rot=({roll:.1f}, {pitch:.1f}, {yaw:.1f})")
        code = arm.set_position(x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw,
                               speed=_stream_state['tcp_speed'], is_radian=False, wait=False)
        print(f"[SEND] Result: {code}")


# ═══════════════════════════════════════════════════════════════════════════════
# Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

# xArm Error Codes (from xArm SDK documentation)
XARM_ERROR_CODES = {
    0: "No error",
    1: "Emergency stop",
    2: "Emergency stop (software)",
    3: "Emergency stop (collision)",
    10: "Servo motor error",
    11: "Servo motor 1 error",
    12: "Servo motor 2 error",
    13: "Servo motor 3 error",
    14: "Servo motor 4 error",
    15: "Servo motor 5 error",
    16: "Servo motor 6 error",
    17: "Servo motor 7 error",
    19: "Joint angle limit exceeded",
    20: "Joint speed limit exceeded",
    21: "Joint torque limit exceeded",
    22: "Joint position deviation too large",
    23: "Position command too large",
    24: "Position command collision detection",
    25: "Cartesian position limit exceeded",
    26: "Linear speed limit exceeded",
    27: "Planning error",
    28: "Servo communication error",
    29: "Control box communication error",
    30: "Motor communication error",
    31: "Teaching mode error",
    32: "Singularity error",
    33: "Arc verification error",
    34: "Incorrect arm direction",
    35: "Self-collision error",
    36: "Joint angle read error",
    37: "Force sensor communication error",
    38: "Force sensor data error",
    39: "Force sensor timeout",
    51: "Linear track error",
    52: "Conveyor belt error",
    60: "Linear speed exceeded limit in servo_j mode",
}

# xArm Warning Codes
XARM_WARN_CODES = {
    0: "No warning",
    1: "Joint angle approaching limit",
    2: "Joint speed approaching limit",
    3: "Joint torque approaching limit",
    10: "Reduced mode active",
    11: "Safe boundary triggered",
}


def _resolve_error_message(err_code: int) -> str:
    """Resolve controller error code to readable text."""
    if err_code in XARM_ERROR_CODES:
        return XARM_ERROR_CODES[err_code]
    try:
        from xarm.core.config.x_code import ControllerError  # pylint: disable=import-outside-toplevel
        return ControllerError(err_code, status=0).title.get('en', f"Unknown error ({err_code})")
    except Exception:
        return f"Unknown error ({err_code})"


def _resolve_warn_message(warn_code: int) -> str:
    """Resolve controller warning code to readable text."""
    if warn_code in XARM_WARN_CODES:
        return XARM_WARN_CODES[warn_code]
    try:
        from xarm.core.config.x_code import ControllerWarn  # pylint: disable=import-outside-toplevel
        return ControllerWarn(warn_code, status=0).title.get('en', f"Unknown warning ({warn_code})")
    except Exception:
        return f"Unknown warning ({warn_code})"


def _append_error_detail(err_code: int, err_msg: str, arm) -> str:
    """Attach detailed SDK diagnostics for known error families."""
    if arm is None:
        return err_msg

    # C60: linear speed limit exceeded in servo-j mode.
    if err_code == 60 and hasattr(arm, "get_c60_error_info"):
        try:
            code, info = arm.get_c60_error_info()
            if code == 0 and isinstance(info, (list, tuple)) and len(info) >= 2:
                max_speed = float(info[0])
                curr_speed = float(info[1])
                return f"{err_msg} (limit {max_speed:.1f} mm/s, current {curr_speed:.1f} mm/s)"
        except Exception:
            pass

    # C24: joint speed limit exceeded.
    if err_code == 24 and hasattr(arm, "get_c24_error_info"):
        try:
            code, info = arm.get_c24_error_info(is_radian=False)
            if code == 0 and isinstance(info, (list, tuple)) and len(info) >= 2:
                servo_id = int(info[0])
                joint_speed = float(info[1])
                return f"{err_msg} (joint {servo_id}, speed {joint_speed:.1f} deg/s)"
        except Exception:
            pass

    return err_msg


def get_error_status():
    """Get current error and warning status from robot."""
    if not _stream_state['active'] or _stream_state['arm'] is None:
        return None, None, "Not connected"

    arm = _stream_state['arm']
    try:
        status = _poll_robot_status(arm)
        if not status['connected']:
            return None, None, "Not connected"

        err_code = int(status['error'])
        warn_code = int(status['warn'])

        err_msg = _append_error_detail(err_code, _resolve_error_message(err_code), arm)
        warn_msg = _resolve_warn_message(warn_code)
        suffix = "" if status.get('sdk_ok', False) else " (poll degraded; using cached values where needed)"

        return err_code, warn_code, f"Error: {err_code} - {err_msg}\nWarn: {warn_code} - {warn_msg}{suffix}"
    except Exception as e:
        return None, None, f"Exception: {e}"


def clear_error():
    """Clear robot errors and warnings."""
    if not _stream_state['active'] or _stream_state['arm'] is None:
        print("[ERROR] Not connected")
        return False

    arm = _stream_state['arm']
    stream_mode = _stream_state['stream_mode']

    try:
        code1 = arm.clean_error()
        code2 = arm.clean_warn()
        code3 = arm.motion_enable(True)
        code4 = arm.set_state(0)

        # Re-enable servo mode if in JOINT mode
        if stream_mode == "JOINT":
            code5 = arm.set_mode(1)
            code6 = arm.set_state(0)
            time.sleep(0.2)
        else:
            code5 = 0
            code6 = 0

        status = _poll_robot_status(arm)
        if any(code != 0 for code in (code1, code2, code3, code4, code5, code6)):
            print(f"[WARN] Clear sequence returned non-zero code(s): {code1},{code2},{code3},{code4},{code5},{code6}")

        if status['error'] != 0:
            print(f"[WARN] Error remains after clear: {status['error']}")
            return False

        print("[INFO] Errors cleared, motion re-enabled")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to clear: {e}")
        return False


def get_robot_state():
    """Get robot state info for display."""
    if not _stream_state['active'] or _stream_state['arm'] is None:
        return {
            'connected': False,
            'error': None,
            'warn': None,
            'state': None,
            'mode': None,
        }

    arm = _stream_state['arm']
    try:
        status = _poll_robot_status(arm)
        if not status['connected']:
            return {
                'connected': False,
                'error': None,
                'warn': None,
                'state': None,
                'mode': None,
            }

        err_code = int(status['error'])
        warn_code = int(status['warn'])
        state = status['state']
        mode = status['mode']

        return {
            'connected': True,
            'error': err_code,
            'error_msg': _append_error_detail(err_code, _resolve_error_message(err_code), arm),
            'warn': warn_code,
            'warn_msg': _resolve_warn_message(warn_code),
            'state': state,
            'mode': mode,
            'sdk_ok': bool(status.get('sdk_ok', False)),
        }
    except Exception as e:
        return {
            'connected': True,
            'error': None,
            'error_msg': f"Exception: {e}",
            'warn': None,
            'warn_msg': "",
            'state': None,
            'mode': None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# UI Operators
# ═══════════════════════════════════════════════════════════════════════════════

class STREAM_OT_Start(bpy.types.Operator):
    bl_idname = "stream.start"
    bl_label = "Start Interactive"
    bl_description = "Start streaming - move bones interactively to control robot"

    def execute(self, context):
        if start_stream(context, timeline_mode=False):
            return {'FINISHED'}
        return {'CANCELLED'}


class STREAM_OT_StartTimeline(bpy.types.Operator):
    bl_idname = "stream.start_timeline"
    bl_label = "Start Timeline"
    bl_description = "Start streaming - play timeline to control robot"

    def execute(self, context):
        if start_stream(context, timeline_mode=True):
            return {'FINISHED'}
        return {'CANCELLED'}


class STREAM_OT_Stop(bpy.types.Operator):
    bl_idname = "stream.stop"
    bl_label = "Stop Stream"

    def execute(self, context):
        stop_stream()
        return {'FINISHED'}


class STREAM_OT_SendOnce(bpy.types.Operator):
    bl_idname = "stream.send_once"
    bl_label = "Send Once"

    def execute(self, context):
        send_once(context)
        return {'FINISHED'}


class STREAM_OT_ClearError(bpy.types.Operator):
    bl_idname = "stream.clear_error"
    bl_label = "Clear Error"
    bl_description = "Clear robot errors and warnings, re-enable motion"

    def execute(self, context):
        if clear_error():
            self.report({'INFO'}, "Errors cleared")
            return {'FINISHED'}
        self.report({'ERROR'}, "Failed to clear errors")
        return {'CANCELLED'}


class STREAM_OT_GetStatus(bpy.types.Operator):
    bl_idname = "stream.get_status"
    bl_label = "Get Status"
    bl_description = "Get current robot error/warning status"

    def execute(self, context):
        err, warn, msg = get_error_status()
        print(f"[STATUS] {msg}")
        if err is not None and err != 0:
            self.report({'WARNING'}, f"Error {err}: {_resolve_error_message(int(err))}")
        elif warn is not None and warn != 0:
            self.report({'WARNING'}, f"Warning {warn}: {_resolve_warn_message(int(warn))}")
        else:
            self.report({'INFO'}, "No errors")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════════════════
# UI Panel
# ═══════════════════════════════════════════════════════════════════════════════

class STREAM_PT_Panel(bpy.types.Panel):
    bl_label = "Real-time Stream"
    bl_idname = "STREAM_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Stream Test"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Status box
        box = layout.box()
        if _stream_state['active']:
            mode_label = "TIMELINE" if _stream_state['timeline_mode'] else "INTERACTIVE"
            box.label(text=f"STREAMING ({mode_label})", icon='REC')
            box.label(text=f"Data: {_stream_state['stream_mode']}")
            box.label(text=f"Armature: {_stream_state['armature_name']}")

            # Robot state
            state = get_robot_state()
            if state['error'] is not None:
                if state['error'] != 0:
                    box.label(text=f"ERROR {state['error']}", icon='ERROR')
                    box.label(text=f"  {state['error_msg']}")
                else:
                    box.label(text="No errors", icon='CHECKMARK')

                if state['warn'] != 0:
                    box.label(text=f"WARN {state['warn']}: {state['warn_msg']}", icon='INFO')

                box.label(text=f"State: {state['state']}, Mode: {state['mode']}")
        else:
            box.label(text="Disconnected", icon='PAUSE')

        # Configuration (only when not streaming)
        if not _stream_state['active']:
            box = layout.box()
            box.label(text="Configuration", icon='SETTINGS')

            # Armature picker
            box.prop(scene, "stream_armature", text="Armature")

            # Robot IP
            box.prop(scene, "stream_robot_ip", text="Robot IP")

            # Robot type
            box.prop(scene, "stream_robot_type", text="Robot Type")

            # Stream mode
            box.prop(scene, "stream_mode", text="Stream Mode")

            # TCP bone (only for TCP mode)
            if scene.stream_mode == 'TCP':
                box.prop(scene, "stream_tcp_bone", text="TCP Bone")

            # Speed settings
            row = box.row()
            row.prop(scene, "stream_joint_speed", text="Joint Speed")
            row.prop(scene, "stream_tcp_speed", text="TCP Speed")

        # Controls
        layout.separator()
        if _stream_state['active']:
            layout.operator("stream.stop", icon='SNAP_FACE')
            layout.operator("stream.send_once", icon='EXPORT')
            layout.separator()
            row = layout.row(align=True)
            row.operator("stream.get_status", icon='INFO')
            row.operator("stream.clear_error", icon='FILE_REFRESH')
        else:
            # Start options
            box = layout.box()
            box.label(text="Start Streaming:")
            row = box.row(align=True)
            row.operator("stream.start", icon='BONE_DATA')
            row.operator("stream.start_timeline", icon='PLAY')


# ═══════════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════════

_classes = [
    STREAM_OT_Start,
    STREAM_OT_StartTimeline,
    STREAM_OT_Stop,
    STREAM_OT_SendOnce,
    STREAM_OT_ClearError,
    STREAM_OT_GetStatus,
    STREAM_PT_Panel,
]


def armature_poll(self, obj):
    """Filter for armature objects only."""
    return obj.type == 'ARMATURE'


def register():
    # Register classes
    for cls in _classes:
        bpy.utils.register_class(cls)

    # Register scene properties
    bpy.types.Scene.stream_armature = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Armature",
        description="Armature to stream",
        poll=armature_poll
    )

    bpy.types.Scene.stream_robot_ip = bpy.props.StringProperty(
        name="Robot IP",
        description="Robot IP address (use 'localhost' for simulation)",
        default=DEFAULT_ROBOT_IP
    )

    bpy.types.Scene.stream_robot_type = bpy.props.EnumProperty(
        name="Robot Type",
        description="Robot configuration to use",
        items=[
            ('uf850_twin', 'UF850', 'UFactory 850 robot'),
            ('ufxarm6_twin', 'xArm6', 'UFactory xArm6 robot'),
        ],
        default='uf850_twin'
    )

    bpy.types.Scene.stream_mode = bpy.props.EnumProperty(
        name="Stream Mode",
        description="Data to stream to robot",
        items=[
            ('JOINT', 'Joint Angles', 'Stream joint angles via servo mode'),
            ('TCP', 'TCP Position', 'Stream TCP position via PTP'),
        ],
        default='JOINT'
    )

    bpy.types.Scene.stream_tcp_bone = bpy.props.StringProperty(
        name="TCP Bone",
        description="Bone name for TCP position (for TCP mode)",
        default=DEFAULT_TCP_BONE
    )

    bpy.types.Scene.stream_joint_speed = bpy.props.IntProperty(
        name="Joint Speed",
        description="Joint streaming speed (deg/s)",
        default=DEFAULT_JOINT_SPEED,
        min=1,
        max=180
    )

    bpy.types.Scene.stream_tcp_speed = bpy.props.IntProperty(
        name="TCP Speed",
        description="TCP movement speed (mm/s)",
        default=DEFAULT_TCP_SPEED,
        min=1,
        max=1000
    )

    print("[Stream] Registered - N-sidebar > Stream Test")


def unregister():
    stop_stream()

    # Unregister scene properties
    del bpy.types.Scene.stream_tcp_speed
    del bpy.types.Scene.stream_joint_speed
    del bpy.types.Scene.stream_tcp_bone
    del bpy.types.Scene.stream_mode
    del bpy.types.Scene.stream_robot_type
    del bpy.types.Scene.stream_robot_ip
    del bpy.types.Scene.stream_armature

    # Unregister classes
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


def cleanup_all_handlers():
    """Remove ALL stream handlers (even old references from previous script runs)."""
    # Remove by function name since references change on script reload
    handlers_to_remove = []
    for handler in bpy.app.handlers.depsgraph_update_post:
        if handler.__name__ == 'depsgraph_update_handler':
            handlers_to_remove.append(handler)
    for handler in handlers_to_remove:
        bpy.app.handlers.depsgraph_update_post.remove(handler)
        print(f"[Stream] Removed old depsgraph handler")

    handlers_to_remove = []
    for handler in bpy.app.handlers.frame_change_post:
        if handler.__name__ == 'frame_change_handler':
            handlers_to_remove.append(handler)
    for handler in handlers_to_remove:
        bpy.app.handlers.frame_change_post.remove(handler)
        print(f"[Stream] Removed old frame handler")


if __name__ == "__main__":
    # Aggressive cleanup first - remove ALL old handlers
    cleanup_all_handlers()

    try:
        unregister()
    except:
        pass
    register()

    print("\n" + "="*50)
    print("Real-time Stream")
    print("="*50)
    print("Configure in N-sidebar > Stream Test:")
    print("  - Armature: Select from scene")
    print("  - Robot IP: localhost for simulation")
    print("  - Stream Mode: JOINT or TCP")
    print("")
    print("Streaming modes:")
    print("  Interactive: Move bones to stream")
    print("  Timeline: Play animation to stream")
    print("="*50 + "\n")
