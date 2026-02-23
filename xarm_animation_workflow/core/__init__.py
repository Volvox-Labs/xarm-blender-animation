"""
Core module for xArm Animation Workflow addon

Contains robot configuration, angle conversion, CSV export/import logic.
"""

from .robot_config import XArmRigConfig
from .bone_utils import BoneAngleExtractor
from .csv_export import SpeedCalculator, CSVExporter
from .csv_playback import CSVPlayback

__all__ = [
    'XArmRigConfig',
    'BoneAngleExtractor',
    'SpeedCalculator',
    'CSVExporter',
    'CSVPlayback',
]
