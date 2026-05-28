# Changelog

All notable changes to the xArm Animation Workflow add-on are tracked here.

## Unreleased

- Placement export now writes the scene robot ID (e.g. `"1"`, `"2"`) into the `animation` field instead of the Blender action name. This matches the format Motion Core expects for runtime-to-scene-robot mapping. Old presets written by previous exporter versions (containing Blender action names like `uf850_ani.01Action`) are auto-resolved by Motion Core's preset-key fallback but produce a warning; re-export to clean them up.

## 1.1.0 - 2026-04-09

- Added robot placement JSON import/export in the Scene Export panel.
- Added tolerant robot id matching for placement files (`r1` and `robot1` match).
- Added slot-order fallback for partial placement imports.
- Added warnings when placement robot counts do not match scene robot slots.
- Updated add-on author/maintainer metadata to Wenyi.

## 1.0.0 - Initial

- Rig setup with FK, IK, and Hybrid controls.
- Single baked CSV export.
- Multi-robot scene bundle export.
- Timeline validation for joint speed, TCP speed, and joint limits.
- Collision URDF bundle export.
- CSV playback on xArm hardware.
