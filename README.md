# xArm Blender Animation

Blender addon for UFactory robot animation workflow.

## Features

- Rig Setup: create FK/IK animation rig from robot model
- Mode Switching: Full FK, Full IK, or Hybrid control
- Single Export: baked CSV export for current active action
- Validation: check joint speed / TCP speed / joint limits on current timeline and add markers
- Scene Export: export multi-robot bundle (`scene_metadata.json` + `csv/*.csv`)
- Collision Export: export collection meshes to URDF bundle (`urdf` + floating base + `meshes/stl`)
- Robot Playback: play exported CSV directly on xArm hardware

## Installation

1. Copy addon folder:
   - Source: `<repo>\xarm_animation_workflow`
   - Destination: `%APPDATA%\Blender Foundation\Blender\5.0\extensions\user_default\xarm_animation_workflow`
2. Copy Python SDK folder for playback:
   - Source: `<repo>\xarm`
   - Destination: `<BLENDER_ROOT>\5.0\python\lib\xarm`
   - Example `BLENDER_ROOT`: `D:\BlenderLauncher\daily\blender-5.0.1-stable+daily.a3db93c5b259`
3. Restart Blender.
4. Open panel: `3D View > Sidebar (N) > xArm Animation`.

Notes:
- Installation is folder-copy only for this project.
- Do not install via pip, zip addon install, or extension package install for this workflow.

## Quick Start

1. Setup: open `blender/Ufactory850-ani-workflow.blend`, choose source collection, click `Setup Rig`.
2. Animate: choose FK/IK/Hybrid mode and keyframe controls.
3. Validation: set FPS/range/limits, click `Validate Current Animation`.
4. Single Export: use `Bake & Export CSV`.
5. Scene Export: add robot slots and run `Export Scene Bundle` (always baked per slot).
6. Collision Export: select collision collection, set URDF name/path, export bundle.
7. Playback: set robot IP, select CSV, play.

## Requirements

- Blender 5.0.1+
- UFactory robot
- xArm SDK (for robot playback)

## Documentation

See [xarm_animation_workflow/README.md](xarm_animation_workflow/README.md) for detailed addon usage.

## License

MIT License.
