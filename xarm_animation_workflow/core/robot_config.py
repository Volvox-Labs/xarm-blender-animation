"""
Robot configuration for xArm robots.
Defines bone mapping, rotation axes, joint limits, and velocity constraints.
"""

from typing import Dict, List, Tuple


class XArmRigConfig:
    """Robot-specific configuration for bone mapping and joint limits."""

    ROBOT_CONFIGS = {
        'uf850_twin': {
            'bone_names': ['joint_1', 'joint_2', 'joint_3', 'joint_4', 'joint_5', 'joint_6'],
            'rotation_axes': ['Y', 'Z', '-Z', 'Y', 'Z', 'Y'],  # From animaquinauf/__init__.py:898
            'joint_limits_deg': [
                (-360, 360),   # J1: ±360°
                (-132, 132),   # J2: ±132° (-2.3038 to 2.3038 rad)
                (-242, 3.5),   # J3: -242° to 3.5° (-4.2237 to 0.0611 rad)
                (-360, 360),   # J4: ±360°
                (-124, 124),   # J5: ±124° (-2.1642 to 2.1642 rad)
                (-360, 360),   # J6: ±360°
            ],
            'max_velocity_deg_s': 180.0,  # 3.14 rad/s from URDF
        },
        'ufxarm6_twin': {
            'bone_names': ['joint_1', 'joint_2', 'joint_3', 'joint_4', 'joint_5', 'joint_6'],
            'rotation_axes': ['Y', '-Z', '-Z', 'Y', '-Z', 'Y'],  # From animaquinauf/__init__.py:896
            'joint_limits_deg': [
                (-360, 360),   # J1
                (-132, 132),   # J2
                (-242, 3.5),   # J3
                (-360, 360),   # J4
                (-124, 124),   # J5
                (-360, 360),   # J6
            ],
            'max_velocity_deg_s': 180.0,
        }
    }

    def __init__(self, robot_type: str):
        """
        Initialize robot configuration.

        Args:
            robot_type: Robot configuration key ('uf850_twin' or 'ufxarm6_twin')

        Raises:
            ValueError: If robot_type is not found in ROBOT_CONFIGS
        """
        if robot_type not in self.ROBOT_CONFIGS:
            raise ValueError(f"Unknown robot type: {robot_type}. Available: {list(self.ROBOT_CONFIGS.keys())}")

        config = self.ROBOT_CONFIGS[robot_type]
        self.robot_type = robot_type
        self.bone_names = config['bone_names']
        self.rotation_axes = config['rotation_axes']
        self.joint_limits_deg = config['joint_limits_deg']
        self.max_velocity_deg_s = config['max_velocity_deg_s']
