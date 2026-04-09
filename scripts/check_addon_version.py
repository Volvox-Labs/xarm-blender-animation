"""Verify Blender add-on version metadata is synchronized."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = ROOT / "xarm_animation_workflow" / "__init__.py"
MANIFEST_FILE = ROOT / "xarm_animation_workflow" / "blender_manifest.toml"


def _read_bl_info_version() -> str:
    tree = ast.parse(INIT_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    data = ast.literal_eval(node.value)
                    version = data.get("version")
                    if not isinstance(version, tuple):
                        raise ValueError("bl_info version must be a tuple")
                    return ".".join(str(part) for part in version)
    raise ValueError("Could not find bl_info")


def _read_manifest_version() -> str:
    text = MANIFEST_FILE.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise ValueError("Could not find manifest version")
    return match.group(1)


def main() -> int:
    bl_info_version = _read_bl_info_version()
    manifest_version = _read_manifest_version()
    if bl_info_version != manifest_version:
        print(
            f"Version mismatch: bl_info={bl_info_version}, "
            f"manifest={manifest_version}",
            file=sys.stderr,
        )
        return 1
    print(f"Add-on version OK: {bl_info_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
