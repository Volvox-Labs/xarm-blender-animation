# xArm Animation Workflow

Blender addon for xArm robot animation: rig setup, CSV export, and robot playback.

## Installation

1. Copy `xarm_animation_workflow/` to Blender addons directory
2. Enable in Edit > Preferences > Add-ons
3. Find panel: 3D View > Sidebar (N) > "xArm Animation"

## Workflow

### 1. Setup Rig
1. Open `blender/Ufactory850-ani-workflow.blend` project file (contains pre-configured robot model)
2. Set source collection (e.g., `uf850_twin`)
3. Click **Setup Rig** to create animation armature

### 2. Animate
Choose a mode in the panel:

| Mode | Control | Use Case |
|------|---------|----------|
| Full FK | Rotate blue FK bones | Traditional keyframe animation |
| Full IK | Move orange TCP bone | Position-based animation |
| Hybrid | Rotate J1-J3 + move TCP | Control base pose with IK tip |

### 3. Export
- **Export CSV (No Bake)**: Direct export from current pose
- **Bake & Export CSV**: Bake IK to keyframes, then export

Speed violations (>180 deg/s) show as timeline markers.

### 4. Play on Robot (Optional)
1. Set Robot IP, Mode, Loops
2. Click **Select CSV**
3. Click **Play CSV on Robot**

| Mode | Description |
|------|-------------|
| Cued | Waits at each position (safe) |
| Servo | Streaming playback (real-time) |

**Note**: Localhost (`127.0.0.1`) disables joint limit checks for simulation.

## Requirements

- Blender 4.2+
- xArm SDK (playback only): `pip install xarm-python-sdk`
