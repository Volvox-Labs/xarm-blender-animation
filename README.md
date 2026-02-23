# xArm Blender Animation

Blender addon for xArm/UFactory robot animation workflow.

## Features

- **Rig Setup**: Create FK/IK animation rig from robot model
- **Mode Switching**: Full FK, Full IK, or Hybrid control
- **CSV Export**: Export animations with speed validation
- **Robot Playback**: Play animations directly on xArm hardware

## Installation

1. Download this repository (Code > Download ZIP)
2. Copy the `xarm_animation_workflow` folder to your Blender addons directory:
   - Windows: `%APPDATA%\Blender\4.2\scripts\addons\`
   - macOS: `~/Library/Application Support/Blender/4.2/scripts/addons/`
   - Linux: `~/.config/blender/4.2/scripts/addons/`
3. In Blender: Edit > Preferences > Add-ons > Search "xArm" > Enable
4. Find panel: 3D View > Sidebar (N) > "xArm Animation"

## Quick Start

1. **Setup**: Open `blender/Ufactory850-ani-workflow.blend` → Set source collection → Click "Setup Rig"
2. **Animate**: Choose mode (FK/IK/Hybrid) → Keyframe bones
3. **Export**: Click "Bake & Export CSV"
4. **Play**: Set Robot IP → Select CSV → Play on Robot

## Requirements

- Blender 4.2+
- xArm SDK (playback only): `pip install xarm-python-sdk`

## Documentation

See [xarm_animation_workflow/README.md](xarm_animation_workflow/README.md) for detailed usage.

## License

MIT License - See [LICENSE](LICENSE)
