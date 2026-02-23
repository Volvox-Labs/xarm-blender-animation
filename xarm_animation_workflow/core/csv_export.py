"""
CSV export utilities.
Speed calculation and CSV file writing for xArm animation export.
"""

import csv
from typing import List, Tuple, Optional


class SpeedCalculator:
    """Calculates safe speed percentage from joint velocities."""

    def __init__(self, max_velocity_deg_s: float, fps: float, max_speed_override: Optional[float] = None):
        """
        Initialize speed calculator.

        Args:
            max_velocity_deg_s: Maximum joint velocity in degrees/second
            fps: Frames per second
            max_speed_override: Override default 50% speed cap (optional)
        """
        self.max_velocity = max_velocity_deg_s
        self.frame_time = 1.0 / fps
        self.max_speed_cap = max_speed_override if max_speed_override is not None else 50.0

    def calculate_speed(self, prev_angles: List[float], curr_angles: List[float]) -> Tuple[float, List[float]]:
        """
        Calculate speed percentage based on max joint velocity between frames.

        Args:
            prev_angles: Previous frame joint angles in degrees
            curr_angles: Current frame joint angles in degrees

        Returns:
            Tuple of (speed_pct, per_joint_velocities)
            - speed_pct: Speed percentage (0-100), capped at max_speed_cap
            - per_joint_velocities: Velocity in deg/s for each joint
        """
        velocities = []

        for prev, curr in zip(prev_angles, curr_angles):
            # Calculate angular velocity (deg/s)
            delta = abs(curr - prev)
            velocity = delta / self.frame_time
            velocities.append(velocity)

        # Find max velocity across all joints
        max_vel = max(velocities)

        # Calculate percentage of max velocity
        speed_pct = (max_vel / self.max_velocity) * 100.0

        # Cap at max_speed_cap for safety
        speed_pct = min(speed_pct, self.max_speed_cap)

        return speed_pct, velocities

    def check_speed_warnings(self, velocities: List[float], frame: int, threshold: float = 0.8) -> List[str]:
        """
        Check for joints exceeding velocity threshold.

        Args:
            velocities: Per-joint velocities in deg/s
            frame: Frame number (for warning messages)
            threshold: Warning threshold as fraction of max velocity (default 0.8 = 80%)

        Returns:
            List of warning messages
        """
        warnings = []
        threshold_vel = self.max_velocity * threshold

        for j, vel in enumerate(velocities):
            if vel > threshold_vel:
                warnings.append(
                    f"Frame {frame}, J{j+1}: {vel:.1f} deg/s exceeds {threshold*100:.0f}% threshold ({threshold_vel:.1f} deg/s)"
                )

        return warnings


class CSVExporter:
    """Writes animation frames to CSV file."""

    def __init__(self, filepath: str, include_tcp: bool = False):
        """
        Initialize CSV exporter.

        Args:
            filepath: Output CSV file path
            include_tcp: Whether to include TCP position/orientation columns
        """
        self.filepath = filepath
        self.include_tcp = include_tcp
        self.rows = []

    def add_frame(self, frame: int, time_s: float, angles: List[float],
                  speed: float, tcp_pos: Optional[List[float]] = None,
                  tcp_orn: Optional[List[float]] = None):
        """
        Add a frame to export buffer.

        Args:
            frame: Frame number
            time_s: Timestamp in seconds
            angles: List of 6 joint angles in degrees
            speed: Speed percentage (0-100)
            tcp_pos: TCP position [x, y, z] in meters (optional)
            tcp_orn: TCP orientation [rx, ry, rz] in degrees (optional)
        """
        row = {
            'frame': frame,
            'time_s': f'{time_s:.4f}',
            'j1_deg': f'{angles[0]:.6f}',
            'j2_deg': f'{angles[1]:.6f}',
            'j3_deg': f'{angles[2]:.6f}',
            'j4_deg': f'{angles[3]:.6f}',
            'j5_deg': f'{angles[4]:.6f}',
            'j6_deg': f'{angles[5]:.6f}',
            'speed_pct': f'{speed:.2f}',
        }

        if self.include_tcp and tcp_pos and tcp_orn:
            row.update({
                'tcp_x_m': f'{tcp_pos[0]:.6f}',
                'tcp_y_m': f'{tcp_pos[1]:.6f}',
                'tcp_z_m': f'{tcp_pos[2]:.6f}',
                'tcp_rx_deg': f'{tcp_orn[0]:.6f}',
                'tcp_ry_deg': f'{tcp_orn[1]:.6f}',
                'tcp_rz_deg': f'{tcp_orn[2]:.6f}',
            })

        self.rows.append(row)

    def write(self):
        """Write buffered frames to CSV file."""
        if not self.rows:
            raise ValueError("No frames to export")

        # Determine field names from first row
        fieldnames = list(self.rows[0].keys())

        # Write CSV
        with open(self.filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.rows)
