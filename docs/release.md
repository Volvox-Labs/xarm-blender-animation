# Release Workflow

Use semantic versioning for the Blender add-on.

- Patch: `1.1.1` for bug fixes only.
- Minor: `1.2.0` for backwards-compatible features.
- Major: `2.0.0` for breaking file format, rig, or workflow changes.

Keep these versions in sync:

- `xarm_animation_workflow/__init__.py`: `bl_info["version"]`
- `xarm_animation_workflow/blender_manifest.toml`: `version`
- Git tag: `vX.Y.Z`
- `CHANGELOG.md`

## Build

Run from the repository root:

```powershell
python scripts/check_addon_version.py
blender --command extension validate --source-dir xarm_animation_workflow
blender --command extension build --source-dir xarm_animation_workflow --output-dir dist
```

The built ZIP in `dist/` can be attached to a GitHub Release.

## User Update Options

Recommended now:

1. Publish a GitHub Release with the built ZIP.
2. Users download the ZIP.
3. Users install it from Blender with `Preferences > Extensions > Install from Disk`.

Recommended later:

1. Publish the built extension ZIPs to a GitHub Pages extension repository.
2. Generate repository metadata with Blender's extension repository tooling.
3. Users add the repository URL once in Blender Preferences.
4. Users update from Blender's extension UI.

Developer option:

- Clone this repo directly into Blender's extensions folder and update with `git pull`.
- This is convenient for development but not recommended for non-technical users.
