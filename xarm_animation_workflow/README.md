# xArm Animation Workflow

Blender addon for **UFactory 850** robot animation: rig setup, single CSV export, multi-robot scene bundle export, collision URDF export, and robot playback.

## Installation

1. Copy `xarm_animation_workflow/` to Blender addons directory
2. Enable in Edit > Preferences > Add-ons
3. Find panel: 3D View > Sidebar (N) > "xArm Animation"

**For robot playback**: Copy the `xarm` library folder into Blender's Python lib folder:
- Windows: `C:\Program Files\Blender Foundation\Blender 5.0\5.0\python\lib\`
- macOS: `/Applications/Blender.app/Contents/Resources/5.0/python/lib/`
- Linux: `/usr/share/blender/5.0/python/lib/`

## Panels

The addon provides five panels in `View3D > Sidebar > xArm Animation`:

1. `Rig Setup & Control`
2. `Single Export`
3. `Scene Export`
4. `Playback`
5. `Collision Export`

## Workflow

### 1. Setup Rig
1. Open `blender/Ufactory850-ani-workflow.blend` project file (contains pre-configured UFactory 850 model)
2. Set source collection (e.g., `uf850_twin`)
3. Click **Setup Rig** to create animation armature

### 2. Animate
Choose a mode in the panel:

| Mode | Control | Use Case |
|------|---------|----------|
| Full FK | Rotate blue FK bones | Traditional keyframe animation |
| Full IK | Move orange TCP bone | Position-based animation |
| Hybrid | Rotate J1-J3 + move TCP | Control base pose with IK tip |

### 3. Single Export
- **Export CSV (No Bake)**: direct export from current rig evaluation
- **Bake & Export CSV**: visual-key bake, then export
- Uses the armature's **active action** (no manual action picker in UI)

Speed violations (>180 deg/s) show as timeline markers.

### 4. Scene Export (Multi-Robot Bundle)
Scene Export writes one folder with:
1. `scene_metadata.json`
2. `csv/*.csv` (one file per robot slot)

Notes:
- Add robot slots, then set `ID` + `Collection` for each.
- Scene Export always performs **bake+export** per slot.
- Uses each armature's **active action**.
- Metadata includes per-robot validation summary.

Current metadata keys:
- Top-level: `scene_name`, `export_source`, `exported_at`, `output_folder`, `frame_range`, `fps`, `robots`, optional `skipped`
- Per robot: `id`, `collection`, `armature`, `transform.rotateXYZ`, `transform.translate`, `animation.path`, `animation.length_frames`, `animation.fps`, `animation.action`, `validation.*`

### 5. Play on Robot (Optional)
1. Set Robot IP, Mode, Loops
2. Click **Select CSV**
3. Click **Play CSV on Robot**

| Mode | Description |
|------|-------------|
| Cued | Waits at each position (safe) |
| Servo | Streaming playback (real-time) |

**Note**: Localhost (`127.0.0.1`) disables joint limit checks for simulation.

### 6. Collision Export (URDF Bundle)
Collision Export writes one folder with:
1. `urdf/<urdf_name>.urdf`
2. `submodels/floating_base/urdf/floatingbase.urdf`
3. `meshes/stl/*.stl`

Notes:
- Select collection (default expected name: `collision`).
- Uses fixed link name `new_link` in URDF.
- Uses Phobos-like output: visual can be box or mesh, collision is exported as box primitives for robust loader compatibility.
- Mesh references include `scale="1 1 1"` and point to `meshes/stl`.
- Includes floating-base freeflyer chain in `floatingbase.urdf`.
- Adds explicit `<inertial>` blocks on exported links to avoid PyBullet "No inertial data for link" warnings.

## Requirements

- Blender 5.0.1+
- UFactory 850 robot
- xArm SDK (for robot playback)
