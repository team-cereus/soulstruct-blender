"""Remove previously equipped weapon objects from the scene."""

from __future__ import annotations

import bpy

from .debug_log import stan_debug, stan_info

__all__ = ["unequip_active_weapon", "tag_weapon_objects"]


def _iter_active_weapon_objects(context: bpy.types.Context) -> list[bpy.types.Object]:
    return [obj for obj in context.scene.objects if obj.get("stan_active_weapon")]


def tag_weapon_objects(context: bpy.types.Context, root: bpy.types.Object) -> None:
    """Mark weapon armature and mesh children with ``stan_active_weapon``."""
    root["stan_active_weapon"] = True
    for child in root.children_recursive:
        child["stan_active_weapon"] = True


def unequip_active_weapon(context: bpy.types.Context, operator=None) -> int:
    """Delete all objects tagged with ``stan_active_weapon``. Returns count removed."""
    targets = _iter_active_weapon_objects(context)
    if not targets:
        return 0

    # Delete root armatures first; children may be unlinked separately.
    armatures = [obj for obj in targets if obj.type == "ARMATURE"]
    others = [obj for obj in targets if obj.type != "ARMATURE"]
    removed = 0

    for obj in armatures + others:
        if obj.name not in context.scene.objects:
            continue
        stan_debug(operator, f"Unequipping weapon object {obj.name!r}")
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1

    if removed:
        stan = getattr(context.scene, "stan_tools_settings", None)
        if stan is not None:
            stan.weapon_stem = ""
            stan.weapon_row_id = ""
        stan_info(operator, f"Removed {removed} previous weapon object(s).")
    return removed
