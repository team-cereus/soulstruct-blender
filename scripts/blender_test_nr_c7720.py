r"""Headless Blender test: Nightreign character FLVER import (and draw-mask export round trip) via the Soulstruct add-on.

Needs the add-on installed in Blender's user add-ons (installer or dev junctions), with its packages pip-installed by a
first enable. Run (PowerShell):

    & 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background `
        --python 'S:\_modding\tools\soulstruct-blender\scripts\blender_test_nr_c7720.py'

Environment variables:

    NR_GAME_ROOT     Nightreign 'Game' folder; only needs oo2core_6_win64.dll (default: Steam install on S:).
    NR_PROJECT_ROOT  Unpacked folder containing chr\ (default: NR_GAME_ROOT).
    NR_CHR           Character model (default c7720).
    NR_EXPORT        "1" (default) to also apply the first NpcParam draw mask, export the FLVER and re-import it. The
                     character's files are copied to a temp project folder first, so nothing real is written.
    NR_DRAW_MASK     "0" to export without applying the draw mask.

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

DEFAULT_GAME_ROOT = r"S:\SteamLibrary\steamapps\common\ELDEN RING NIGHTREIGN\Game"


def _setup_addon():
    import addon_utils

    addon_utils.enable("io_soulstruct", default_set=False)
    if not addon_utils.check("io_soulstruct")[1]:
        raise RuntimeError("Could not enable the io_soulstruct add-on (is it installed?).")


def _configure(game_root: Path, project_root: Path, mod_root: Path | None = None):
    import bpy

    settings = bpy.context.scene.soulstruct_settings
    settings.game_enum = os.environ.get("NR_GAME", "NIGHTREIGN")  # ELDEN_RING to compare against upstream
    settings.game_settings.game_root_str = str(game_root)
    settings.game_settings.project_root_str = str(project_root)
    settings.game_settings.mod_root_str = str(mod_root or "")
    settings.prefer_import_from_project = True
    settings.also_export_to_game = False  # exports must only ever land in the (temp) project folder
    bpy.context.scene.flver_import_settings.import_textures = True
    return settings


def _clear_scene():
    import bpy

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)


def _import_character(chr_id: str, project_root: Path):
    import bpy

    result = bpy.ops.import_scene.character_flver(
        directory=str(project_root / "chr"), files=[{"name": f"{chr_id}.chrbnd.dcx"}]
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"import_scene.character_flver returned {result}")
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(chr_id)]
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE" and o.name.startswith(chr_id)]
    if len(meshes) != 1 or len(armatures) != 1:
        raise RuntimeError(f"Expected one mesh and one armature, got {meshes} / {armatures}")
    return meshes[0], armatures[0]


def _copy_character_files(source_root: Path, chr_id: str, dest_root: Path):
    (dest_root / "chr").mkdir(parents=True)
    for path in (source_root / "chr").glob(f"{chr_id}*"):
        shutil.copy2(path, dest_root / "chr" / path.name)


def _mesh_stats(mesh) -> tuple[int, int, int]:
    return len(mesh.data.vertices), len(mesh.data.polygons), len(mesh.data.materials)


def main() -> int:
    import bpy

    game_root = Path(os.environ.get("NR_GAME_ROOT", DEFAULT_GAME_ROOT))
    project_root = Path(os.environ.get("NR_PROJECT_ROOT", game_root))
    chr_id = os.environ.get("NR_CHR", "c7720")
    chrbnd = project_root / "chr" / f"{chr_id}.chrbnd.dcx"
    if not chrbnd.is_file():
        print(f"FAIL: CHRBND not found: {chrbnd}")
        return 1

    _setup_addon()
    settings = _configure(game_root, project_root)
    print(f"read_flvers_with_pyrelink={settings.read_flvers_with_pyrelink} use_pyrelink_flver (export)={settings.use_pyrelink_flver}")
    _clear_scene()
    mesh, armature = _import_character(chr_id, project_root)
    missing = [i.name for i in bpy.data.images if tuple(i.size) == (1, 1)]
    print(
        f"OK import: mesh={mesh.name} verts/faces/materials={_mesh_stats(mesh)} bones={len(armature.data.bones)} "
        f"images={len(bpy.data.images)} placeholder_images={len(missing)}"
    )

    if os.environ.get("NR_EXPORT", "1") != "1":
        return 0

    with tempfile.TemporaryDirectory(prefix="nr_flver_export_") as temp:
        temp_project = Path(temp, "project")
        _copy_character_files(project_root, chr_id, temp_project)
        _configure(game_root, temp_project)
        _clear_scene()
        mesh, armature = _import_character(chr_id, temp_project)

        stan = bpy.context.scene.stan_tools_settings
        masked = False
        if os.environ.get("NR_DRAW_MASK", "1") != "1":
            print("draw mask skipped (NR_DRAW_MASK=0)")
        elif stan.refresh_npc_param_list(bpy.context, chr_id):
            bpy.context.view_layer.objects.active = mesh
            result = bpy.ops.stan_tools.apply_npc_param_draw_mask()
            masked = result == {"FINISHED"}
            print(f"draw mask applied: {result}")
        else:
            print("no NpcParam rows for this character; exporting without a draw mask")

        before = _mesh_stats(mesh)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh
        result = bpy.ops.export_scene.character_flver()
        if result != {"FINISHED"}:
            print(f"FAIL: export_scene.character_flver returned {result}")
            return 1
        from soulstruct.containers import Binder

        exported = Binder.from_path(temp_project / "chr" / f"{chr_id}.chrbnd.dcx")
        flver_data = exported.find_entries_by_name_regex(r".*\.flver(\.dcx)?")[0].get_uncompressed_data()
        print(f"exported FLVER version: 0x{int.from_bytes(flver_data[8:12], 'little'):x}")

        _clear_scene()
        mesh, armature = _import_character(chr_id, temp_project)
        after = _mesh_stats(mesh)
        print(f"OK export round trip (draw mask: {masked}): before={before} after={after}")
        if before[1:] != after[1:]:
            print("FAIL: face or material count changed in the FLVER export round trip")
            return 1
    return 0


if __name__ == "__main__":  # `multiprocessing` workers re-import this file without running it
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
