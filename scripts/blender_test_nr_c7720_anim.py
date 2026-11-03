r"""Headless Blender test: Nightreign character animation import -> export (Auto-Repack) -> re-import round trip.

Drives the Soulstruct add-on (Stan's Tools 'Search Character Animation' and 'Export Character Anim'), so the add-on
must be installed in Blender's user add-ons with its packages pip-installed. Run (PowerShell):

    & 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background `
        --python 'S:\_modding\tools\soulstruct-blender\scripts\blender_test_nr_c7720_anim.py'

Environment variables:

    NR_GAME_ROOT     Nightreign 'Game' folder; only needs oo2core_6_win64.dll (default: Steam install on S:).
    NR_PROJECT_ROOT  Unpacked folder containing chr\ (default: NR_GAME_ROOT). The character's files are copied to a
                     temp project + mod folder first, so the export never writes anywhere real.
    NR_CHR           Character model (default c7720). Its ANIBND must not be split into BLF '_div' binders.
    NR_ANIM_STEM     Animation entry stem (default a000_000020, else the first animation in the ANIBND).
    NR_TOLERANCE     Max allowed difference in bone location (m) and rotation (degrees) (default 0.01 / 0.5).

Exits 0 on success, 1 on failure.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from blender_test_nr_c7720 import DEFAULT_GAME_ROOT, _clear_scene, _configure, _copy_character_files, _import_character, _setup_addon  # noqa: E402


def _sample_pose(armature, frames: list[int]) -> dict[int, dict[str, tuple]]:
    import bpy

    samples = {}
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        samples[frame] = {
            bone.name: (bone.matrix.to_translation(), bone.matrix.to_quaternion()) for bone in armature.pose.bones
        }
    return samples


def _import_animation(chr_id: str, armature, mesh, stem: str | None):
    import bpy
    from io_soulstruct.soulstruct.blender.stan_tools.animation_search import (
        StanSearchCharacterAnimation,
        build_character_animation_search_items,
    )

    bpy.context.view_layer.objects.active = armature
    items = build_character_animation_search_items(bpy.context)
    StanSearchCharacterAnimation._search_items = items
    choices = [item for item in items if item[0]]
    if not choices:
        project = Path(bpy.context.scene.soulstruct_settings.game_settings.project_root_str)
        raise RuntimeError(
            f"No animations found for {chr_id}: {items} (project {project}: {sorted(p.name for p in project.glob('chr/*'))})"
        )
    chosen = next((item for item in choices if stem and stem in item[1]), choices[0])
    result = bpy.ops.stan_tools.search_character_animation(animation_entry_id=chosen[0])
    if result != {"FINISHED"}:
        raise RuntimeError(f"stan_tools.search_character_animation returned {result}")
    action = armature.animation_data.action if armature.animation_data else None
    if action is None:
        raise RuntimeError("No action on the armature after animation import.")
    return chosen, action


def main() -> int:
    import bpy

    game_root = Path(os.environ.get("NR_GAME_ROOT", DEFAULT_GAME_ROOT))
    source_root = Path(os.environ.get("NR_PROJECT_ROOT", game_root))
    chr_id = os.environ.get("NR_CHR", "c7720")
    stem = os.environ.get("NR_ANIM_STEM", "a000_000020")
    max_loc, max_deg = (float(x) for x in os.environ.get("NR_TOLERANCE", "0.01/0.5").split("/"))
    if not (source_root / "chr" / f"{chr_id}.anibnd.dcx").is_file():
        print(f"FAIL: ANIBND not found: {source_root / 'chr' / f'{chr_id}.anibnd.dcx'}")
        return 1

    _setup_addon()
    with tempfile.TemporaryDirectory(prefix="nr_anim_roundtrip_") as temp:
        project_root, mod_root = Path(temp, "project"), Path(temp, "mod")
        _copy_character_files(source_root, chr_id, project_root)
        _configure(game_root, project_root, mod_root)
        bpy.context.scene.animation_export_settings.auto_repack_to_mod = True
        _clear_scene()
        mesh, armature = _import_character(chr_id, project_root)

        chosen, action = _import_animation(chr_id, armature, mesh, stem)
        start, end = (int(f) for f in action.frame_range)
        frames = sorted({start, (start + end) // 2, end})
        print(f"OK animation import: entry {chosen[1]!r} action={action.name!r} frames={start}-{end}")
        before = _sample_pose(armature, frames)

        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        result = bpy.ops.export_scene.hkx_character_animation()
        if result != {"FINISHED"}:
            print(f"FAIL: export_scene.hkx_character_animation returned {result}")
            return 1
        repacked = mod_root / "chr" / f"{chr_id}.anibnd.dcx"
        print(f"OK animation export: Auto-Repack copy {'exists' if repacked.is_file() else 'MISSING'} at {repacked}")
        if not repacked.is_file():
            return 1

        armature.animation_data.action = None
        bpy.data.actions.remove(action)
        _, action = _import_animation(chr_id, armature, mesh, stem)
        after = _sample_pose(armature, frames)

        worst_loc = worst_deg = 0.0
        worst_bone = ""
        for frame in frames:
            for name, (loc, rot) in before[frame].items():
                loc2, rot2 = after[frame][name]
                d_loc = (loc - loc2).length
                d_deg = math.degrees(rot.rotation_difference(rot2).angle)
                d_deg = min(d_deg, 360.0 - d_deg)
                if d_loc > worst_loc or d_deg > worst_deg:
                    worst_bone = f"{name} @ frame {frame}"
                worst_loc, worst_deg = max(worst_loc, d_loc), max(worst_deg, d_deg)
        print(
            f"pose diff after round trip over frames {frames}: max location {worst_loc:.5f} m, "
            f"max rotation {worst_deg:.3f} deg (worst: {worst_bone})"
        )
        if worst_loc > max_loc or worst_deg > max_deg:
            print("FAIL: round-trip pose differs beyond tolerance")
            return 1
        print("OK animation round trip")
    return 0


if __name__ == "__main__":  # `multiprocessing` workers re-import this file without running it
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
