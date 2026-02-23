"""
Bone angle extraction utilities.
Reads Blender armature bone rotations and converts to xArm joint angles.
"""

import bpy
import math
from typing import List, Tuple

from .robot_config import XArmRigConfig


class BoneAngleExtractor:
    """Extracts joint angles from Blender armature bones."""

    def __init__(self, armature_name: str, config: XArmRigConfig):
        """
        Initialize bone angle extractor.

        Args:
            armature_name: Name of armature object in Blender scene
            config: Robot configuration

        Raises:
            ValueError: If armature not found or not an armature object
        """
        self.armature_name = armature_name
        self.config = config

        # Validate armature exists
        self.armature_obj = bpy.data.objects.get(armature_name)
        if self.armature_obj is None:
            raise ValueError(f"Armature '{armature_name}' not found in scene")
        if self.armature_obj.type != 'ARMATURE':
            raise ValueError(f"Object '{armature_name}' is not an armature (type: {self.armature_obj.type})")

        # Validate all bones exist
        missing_bones = []
        for bone_name in self.config.bone_names:
            if bone_name not in self.armature_obj.pose.bones:
                missing_bones.append(bone_name)

        if missing_bones:
            raise ValueError(f"Missing bones in armature '{armature_name}': {missing_bones}")

    def get_joint_angles(self, frame: int) -> List[float]:
        """
        Read bone rotations for given frame and return joint angles in degrees.

        This reverses the logic in animaquinauf/__init__.py:update_twin_angles()
        which SETS bone rotations FROM joint angles. Here we READ bone rotations
        and output joint angles.

        Args:
            frame: Frame number to read

        Returns:
            List of 6 joint angles in degrees [j1, j2, j3, j4, j5, j6]
        """
        # Set scene to specified frame
        bpy.context.scene.frame_set(frame)

        joint_angles = []

        for i, (bone_name, axis) in enumerate(zip(self.config.bone_names, self.config.rotation_axes)):
            # Get bone from armature
            bone = self.armature_obj.pose.bones[bone_name]

            # Ensure rotation mode is Euler XYZ
            bone.rotation_mode = 'XYZ'

            # Determine axis index and sign
            if axis.startswith('-'):
                sign = -1
                axis_char = axis[1:]  # Remove '-' prefix
            else:
                sign = 1
                axis_char = axis

            # Map axis character to index
            axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[axis_char]

            # Extract rotation in radians, convert to degrees, apply sign
            angle_rad = bone.rotation_euler[axis_idx]
            angle_deg = math.degrees(angle_rad) * sign

            joint_angles.append(angle_deg)

        return joint_angles

    def validate_limits(self, angles: List[float], frame: int) -> Tuple[bool, List[str]]:
        """
        Check if joint angles are within limits.

        Args:
            angles: List of 6 joint angles in degrees
            frame: Frame number (for error messages)

        Returns:
            Tuple of (is_valid, error_messages)
            - is_valid: True if all angles within limits
            - error_messages: List of violation descriptions
        """
        is_valid = True
        errors = []

        for j, (angle, (min_lim, max_lim)) in enumerate(zip(angles, self.config.joint_limits_deg)):
            if angle < min_lim or angle > max_lim:
                is_valid = False
                errors.append(
                    f"Frame {frame}, J{j+1}: {angle:.2f}° exceeds limit [{min_lim:.1f}°, {max_lim:.1f}°]"
                )

        return is_valid, errors
