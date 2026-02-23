"""
CSV Playback for xArm Robot

Provides CSVPlayback class for playing exported animations on real robot.
Supports both cued (safe) and servo (streaming) modes.
"""

import csv
import math
import time
from typing import List, Dict, Optional, Callable


class CSVPlayback:
    """Plays CSV animation on xArm robot."""

    def __init__(self, robot_ip: str, max_vel_deg_s: float = 180.0):
        """
        Initialize playback handler.

        Args:
            robot_ip: Robot IP address
            max_vel_deg_s: Maximum velocity in deg/s (for speed mapping)
        """
        self.robot_ip = robot_ip
        self.max_vel_deg_s = max_vel_deg_s
        self._arm = None
        self._alive = True
        self._angle_acc = 500
        self._progress_callback: Optional[Callable[[int, int, str], None]] = None

    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """Set callback for progress updates: callback(current_frame, total_frames, message)"""
        self._progress_callback = callback

    def _is_localhost(self) -> bool:
        """Check if robot IP is localhost (simulation mode)."""
        return self.robot_ip in ('localhost', '127.0.0.1', '::1')

    def _report_progress(self, current: int, total: int, message: str = ""):
        """Report progress to callback if set."""
        if self._progress_callback:
            self._progress_callback(current, total, message)

    def connect(self) -> bool:
        """
        Connect to robot.

        Returns:
            True if connected successfully
        """
        try:
            from xarm.wrapper import XArmAPI
        except ImportError:
            raise ImportError(
                "xArm SDK not installed. Install with: pip install xarm-python-sdk"
            )

        try:
            # Localhost/simulation: disable checks for faster connection
            # Real robot: enable safety checks
            is_simulation = self._is_localhost()

            if is_simulation:
                # Simulation mode - skip all checks
                self._arm = XArmAPI(
                    self.robot_ip,
                    baud_checkset=False,
                    check_joint_limit=False
                )
            else:
                # Real robot - use defaults for safety (baud_checkset=True, check_joint_limit=True)
                self._arm = XArmAPI(self.robot_ip)

            if is_simulation:
                print("[INFO] Localhost detected - joint limit checking DISABLED (simulation mode)")
            else:
                print("[INFO] Real robot IP - joint limit checking ENABLED (safety mode)")

            self._arm.clean_warn()
            self._arm.clean_error()
            self._arm.motion_enable(True)
            self._arm.set_mode(0)
            self._arm.set_state(0)
            time.sleep(1)

            # Register callbacks
            self._arm.register_error_warn_changed_callback(self._error_callback)
            self._arm.register_state_changed_callback(self._state_callback)

            return self._arm.connected and self._arm.error_code == 0

        except Exception as e:
            print(f"[ERROR] Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from robot."""
        if self._arm:
            try:
                self._arm.release_error_warn_changed_callback(self._error_callback)
                self._arm.release_state_changed_callback(self._state_callback)
                self._arm.disconnect()
            except:
                pass
            self._arm = None

    def _error_callback(self, data):
        """Handle robot errors."""
        if data and data.get('error_code', 0) != 0:
            self._alive = False
            print(f"[ERROR] Robot error: {data['error_code']}")

    def _state_callback(self, data):
        """Handle robot state changes."""
        if data and data.get('state', 0) == 4:
            self._alive = False
            print("[ERROR] Robot entered error state")

    @property
    def is_alive(self) -> bool:
        """Check if robot is still operational."""
        if not self._alive or not self._arm:
            return False
        return self._arm.connected and self._arm.error_code == 0 and self._arm.state < 4

    def load_csv(self, filepath: str) -> List[Dict]:
        """
        Load animation from CSV file.

        Args:
            filepath: Path to CSV file

        Returns:
            List of row dictionaries
        """
        with open(filepath, newline='') as f:
            rows = list(csv.DictReader(f))

        if not rows:
            raise ValueError(f"CSV file is empty: {filepath}")

        # Validate required columns
        required = ['frame', 'time_s', 'j1_deg', 'j2_deg', 'j3_deg', 'j4_deg', 'j5_deg', 'j6_deg', 'speed_pct']
        missing = [c for c in required if c not in rows[0]]
        if missing:
            raise ValueError(f"CSV missing columns: {missing}")

        return rows

    def _angles_from_row(self, row: Dict) -> List[float]:
        """Extract joint angles from CSV row."""
        return [float(row[f'j{i}_deg']) for i in range(1, 7)]

    def _speed_deg_s(self, row: Dict) -> float:
        """Map speed_pct to deg/s for cued mode."""
        pct = float(row['speed_pct'])
        return max(1.0, (pct / 100.0) * self.max_vel_deg_s)

    def _speed_rad_s(self, row: Dict) -> float:
        """Map speed_pct to rad/s for servo mode."""
        pct = float(row['speed_pct'])
        return max(0.01, (pct / 100.0) * math.radians(self.max_vel_deg_s))

    def play_cued(self, rows: List[Dict], loops: int = 1, move_to_first: bool = True) -> bool:
        """
        Play animation in cued mode (safe, waits for each position).

        Args:
            rows: CSV rows from load_csv()
            loops: Number of times to play
            move_to_first: Move to start position first

        Returns:
            True if completed successfully
        """
        if not self.is_alive:
            print("[ERROR] Robot not connected or in error state")
            return False

        self._arm.set_mode(0)
        self._arm.set_state(0)
        time.sleep(0.5)

        total_frames = len(rows) * loops

        # Move to start
        if move_to_first:
            self._report_progress(0, total_frames, "Moving to start position...")
            angles = self._angles_from_row(rows[0])
            speed = self._speed_deg_s(rows[0])
            code = self._arm.set_servo_angle(
                angle=angles, speed=speed,
                mvacc=self._angle_acc, wait=True, radius=-1.0
            )
            if code != 0:
                print(f"[ERROR] Failed to move to start: code={code}")
                return False

        # Play loops
        frame_idx = 0
        for loop in range(loops):
            self._report_progress(frame_idx, total_frames, f"Loop {loop + 1}/{loops}")

            for i, row in enumerate(rows):
                if not self.is_alive:
                    return False

                angles = self._angles_from_row(row)
                speed = self._speed_deg_s(row)

                code = self._arm.set_servo_angle(
                    angle=angles, speed=speed,
                    mvacc=self._angle_acc, wait=True, radius=-1.0
                )
                if code != 0:
                    print(f"[ERROR] Frame {row['frame']} failed: code={code}")
                    return False

                frame_idx += 1
                self._report_progress(frame_idx, total_frames, f"Frame {row['frame']}")

        self._report_progress(total_frames, total_frames, "Complete")
        return True

    def play_servo(self, rows: List[Dict], loops: int = 1, move_to_first: bool = True) -> bool:
        """
        Play animation in servo mode (streaming, real-time).

        Args:
            rows: CSV rows from load_csv()
            loops: Number of times to play
            move_to_first: Move to start position first

        Returns:
            True if completed successfully
        """
        if not self.is_alive:
            print("[ERROR] Robot not connected or in error state")
            return False

        # Calculate frame interval from timestamps
        if len(rows) >= 2:
            dt = float(rows[1]['time_s']) - float(rows[0]['time_s'])
        else:
            dt = 1.0 / 30.0

        total_frames = len(rows) * loops

        # Move to start safely (mode 0)
        if move_to_first:
            self._arm.set_mode(0)
            self._arm.set_state(0)
            time.sleep(0.3)

            self._report_progress(0, total_frames, "Moving to start position...")
            angles = self._angles_from_row(rows[0])
            code = self._arm.set_servo_angle(
                angle=angles, speed=30.0,
                mvacc=self._angle_acc, wait=True, radius=-1.0
            )
            if code != 0:
                print(f"[ERROR] Failed to move to start: code={code}")
                return False

        # Switch to servo mode
        self._arm.set_mode(1)
        self._arm.set_state(0)
        time.sleep(0.3)

        # Play loops
        frame_idx = 0
        for loop in range(loops):
            self._report_progress(frame_idx, total_frames, f"Loop {loop + 1}/{loops} (servo)")
            loop_start = time.monotonic()

            for i, row in enumerate(rows):
                if not self.is_alive:
                    return False

                frame_deadline = loop_start + float(row['time_s'])
                angles = self._angles_from_row(row)
                speed = self._speed_rad_s(row)

                code = self._arm.set_servo_angle_j(
                    angles, speed=speed, mvacc=1000, wait=False
                )
                if code != 0:
                    print(f"[ERROR] Frame {row['frame']} failed: code={code}")
                    return False

                # Sleep until deadline
                now = time.monotonic()
                sleep_time = frame_deadline - now
                if sleep_time > 0:
                    time.sleep(sleep_time)

                frame_idx += 1

            self._report_progress(frame_idx, total_frames, f"Loop {loop + 1} complete")

        self._report_progress(total_frames, total_frames, "Complete")
        return True

    def stop(self):
        """Emergency stop - set alive to False."""
        self._alive = False
        if self._arm:
            try:
                self._arm.set_state(4)  # Stop
            except:
                pass
