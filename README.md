# xArm Blender Animation

Blender addon for **UFactory 850** robot animation workflow.

## Features

- **Rig Setup**: Create FK/IK animation rig from robot model
- **Mode Switching**: Full FK, Full IK, or Hybrid control
- **CSV Export**: Export animations with speed validation
- **Robot Playback**: Play animations directly on xArm hardware

## Installation

### 1. Install xArm SDK into Blender Python

For robot playback functionality, copy the xArm library into Blender's Python folder:

1. Install xArm SDK to get the library files:
   ```
   pip install xarm-python-sdk
   ```

2. Locate your Python site-packages folder (where `xarm` was installed)

3. Copy the `xarm` folder into Blender's Python lib folder:
   - Windows: `C:\Program Files\Blender Foundation\Blender 5.0\5.0\python\lib\`
   - macOS: `/Applications/Blender.app/Contents/Resources/5.0/python/lib/`
   - Linux: `/usr/share/blender/5.0/python/lib/`

> **Tip**: Use [Blender Launcher](https://github.com/DotBow/Blender-Launcher) to keep an isolated version of Blender and Python.

### 2. Install the Addon

1. Download this repository (Code > Download ZIP)
2. Copy the `xarm_animation_workflow` folder to your Blender addons directory:
   - Windows: `%APPDATA%\Blender\5.0\scripts\addons\`
   - macOS: `~/Library/Application Support/Blender/5.0/scripts/addons/`
   - Linux: `~/.config/blender/5.0/scripts/addons/`
3. In Blender: Edit > Preferences > Add-ons > Search "xArm" > Enable
4. Find panel: 3D View > Sidebar (N) > "xArm Animation"

## Quick Start

1. **Setup**: Open `blender/Ufactory850-ani-workflow.blend` → Set source collection → Click "Setup Rig"
2. **Animate**: Choose mode (FK/IK/Hybrid) → Keyframe bones
3. **Export**: Click "Bake & Export CSV"
4. **Play**: Set Robot IP → Select CSV → Play on Robot

## Requirements

- Blender 5.0.1+
- UFactory 850 robot
- xArm SDK (for robot playback)

## Documentation

See [xarm_animation_workflow/README.md](xarm_animation_workflow/README.md) for detailed usage.

## License

MIT License - See [LICENSE](LICENSE)
