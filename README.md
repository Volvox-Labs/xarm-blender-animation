# xArm Blender Animation

Blender addon for UFactory robot animation workflow.

## Features

- Rig Setup: create FK/IK animation rig from robot model
- Mode Switching: Full FK, Full IK, or Hybrid control
- Single Export: export animation to CSV (direct or baked) with speed validation
- Scene Export: export multi-robot bundle (`scene_metadata.json` + `csv/*.csv`)
- Robot Playback: play exported CSV directly on xArm hardware

## Installation

### 1. Install xArm SDK into Blender Python

For robot playback functionality, copy the xArm library into Blender's Python folder.

1. Install xArm SDK to get the library files:
   ```bash
   pip install xarm-python-sdk
   ```
2. Locate your Python site-packages folder (where `xarm` was installed).
3. Copy the `xarm` folder into Blender's Python lib folder:
   - Windows: `C:\Program Files\Blender Foundation\Blender 5.0\5.0\python\lib\`
   - macOS: `/Applications/Blender.app/Contents/Resources/5.0/python/lib/`
   - Linux: `/usr/share/blender/5.0/python/lib/`

### 2. Install the Addon

1. Download this repository.
2. Copy `xarm_animation_workflow` to your Blender addons directory.
3. In Blender: `Edit > Preferences > Add-ons` and enable xArm addon.
4. Open panel: `3D View > Sidebar (N) > xArm Animation`.

## Quick Start

1. Setup: open `blender/Ufactory850-ani-workflow.blend`, choose source collection, click `Setup Rig`.
2. Animate: choose FK/IK/Hybrid mode and keyframe controls.
3. Single Export: use `Export CSV (No Bake)` or `Bake & Export CSV`.
4. Scene Export: add robot slots and run `Export Scene Bundle` (always baked per slot).
5. Playback: set robot IP, select CSV, play.

## Requirements

- Blender 5.0.1+
- UFactory robot
- xArm SDK (for robot playback)

## Documentation

See [xarm_animation_workflow/README.md](xarm_animation_workflow/README.md) for detailed addon usage.

## License

MIT License.
