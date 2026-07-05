"""Filtered weapon PARTSBND import (primary FLVER only)."""

from __future__ import annotations

import re
import traceback
from pathlib import Path

import bpy

from soulstruct.containers import Binder
from soulstruct.flver import FLVER

from soulstruct.blender.flver.image.image_import_manager import ImageImportManager
from soulstruct.blender.flver.models.types import BlenderFLVER
from soulstruct.blender.flver.utilities import get_flvers_from_binder
from soulstruct.blender.utilities import find_or_create_collection

from .debug_log import stan_debug, stan_info, stan_warning
from .unequip_weapon import tag_weapon_objects

__all__ = [
    "import_weapon_partsbnd",
    "is_primary_weapon_flver_stem",
    "hide_weapon_variant_armatures",
]

_WEAPON_PARTS_BND_RE = re.compile(r"^(WP_A_\d{4})\.partsbnd", re.IGNORECASE)
_WEAPON_VARIANT_FLVER_RE = re.compile(r"^WP_A_\d{4}_\d+$", re.IGNORECASE)


def is_primary_weapon_flver_stem(flver_stem: str, binder_stem: str) -> bool:
    """True when ``flver_stem`` is the primary weapon mesh (not ``WP_A_####_1`` variants)."""
    if flver_stem.lower() == binder_stem.lower():
        return True
    if _WEAPON_VARIANT_FLVER_RE.match(flver_stem):
        return False
    return flver_stem.lower().startswith(binder_stem.lower())


def hide_weapon_variant_armatures(
    context: bpy.types.Context,
    weapon_stem: str,
    operator=None,
) -> int:
    """Hide/disable armatures imported from ``WP_A_####_N`` variant FLVERs."""
    stem_upper = weapon_stem.upper()
    hidden = 0
    prefix = f"{stem_upper}_"
    for obj in context.scene.objects:
        if obj.type != "ARMATURE":
            continue
        name_upper = obj.name.upper()
        if name_upper == stem_upper:
            continue
        if name_upper.startswith(prefix):
            obj.hide_set(True)
            obj.hide_viewport = True
            obj.hide_render = True
            hidden += 1
            stan_debug(operator, f"Hidden weapon variant armature {obj.name!r}")
    if hidden:
        stan_info(operator, f"Hidden {hidden} variant mesh armature(s) for {weapon_stem}.")
    return hidden


def _binder_stem_from_path(partsbnd_path: Path) -> str:
    match = _WEAPON_PARTS_BND_RE.match(partsbnd_path.name)
    if match:
        return match.group(1).upper()
    return partsbnd_path.stem.split(".")[0].upper()


def import_weapon_partsbnd(operator, context: bpy.types.Context, partsbnd_path: Path) -> set[str]:
    """Import weapon PARTSBND keeping only the primary ``WP_A_####`` FLVER mesh."""
    binder_stem = _binder_stem_from_path(partsbnd_path)
    stan_debug(operator, f"Importing weapon PARTSBND (primary FLVER only): {partsbnd_path}")

    try:
        binder = Binder.from_path(partsbnd_path)
    except Exception as ex:
        if operator is not None:
            operator.error(f"Cannot read weapon PARTSBND: {ex}")
        return {"CANCELLED"}

    all_flvers = get_flvers_from_binder(binder, partsbnd_path, allow_multiple=True)
    primary_flvers = [
        (flver.path_minimal_stem, flver)
        for flver in all_flvers
        if is_primary_weapon_flver_stem(flver.path_minimal_stem, binder_stem)
    ]
    skipped = len(all_flvers) - len(primary_flvers)
    if skipped:
        stan_debug(
            operator,
            f"Skipping {skipped} variant FLVER(s) in {partsbnd_path.name} "
            f"(keeping primary {binder_stem}).",
        )

    if not primary_flvers:
        stan_warning(operator, f"No primary FLVER found in {partsbnd_path.name}.")
        if operator is not None:
            operator.error(f"No primary weapon FLVER in {partsbnd_path.name}.")
        return {"CANCELLED"}

    import_settings = context.scene.flver_import_settings
    image_import_manager = ImageImportManager(operator, context)
    if import_settings.import_textures:
        image_import_manager.find_flver_textures(partsbnd_path, binder)

    settings = operator.settings(context)
    collection = find_or_create_collection(context.scene.collection, "Models", "Equipment Models")

    use_matbinbnd = any(flver.version.uses_matbin() for _, flver in primary_flvers)
    bl_flver = None
    for bl_name, flver in primary_flvers:
        if not flver.meshes:
            stan_warning(operator, f"FLVER '{bl_name}' has no meshes (skeleton-only).")
        try:
            bl_flver = BlenderFLVER.new_from_soulstruct_obj(
                operator,
                context,
                flver,
                name=bl_name,
                image_import_manager=image_import_manager,
                collection=collection,
            )
        except Exception as ex:
            tb = traceback.format_exc()
            # Surface the real failure site: the wrapper only saw str(ex) before, which hid
            # where (and what type of) error occurred deep in the FLVER importer.
            stan_warning(operator, f"Weapon FLVER import failed for {bl_name!r}:\n{tb}")
            traceback.print_exc()
            if operator is not None:
                operator.error(
                    f"Cannot import weapon FLVER {bl_name}: {type(ex).__name__}: {ex}"
                )
            return {"CANCELLED"}

    hide_weapon_variant_armatures(context, binder_stem, operator=operator)

    if bl_flver is not None:
        if bl_flver.armature is not None:
            tag_weapon_objects(context, bl_flver.armature)
        operator.set_active_obj(bl_flver.mesh)
        bpy.ops.view3d.view_selected(use_all_regions=False)

    stan_info(operator, f"Imported primary weapon mesh {binder_stem} from {partsbnd_path.name}.")
    return {"FINISHED"}
