"""Scene helpers for locating imported weapon armatures."""

from __future__ import annotations

import bpy

from .debug_log import stan_debug


def find_weapon_armature(
    context: bpy.types.Context,
    weapon_stem: str,
    operator=None,
) -> bpy.types.Object | None:
    """Find armature for ``WP_A_####`` by name prefix or under Equipment Models collection."""
    if not weapon_stem:
        return None

    stem_lower = weapon_stem.lower()
    stan_debug(operator, f"Searching armature for weapon stem {weapon_stem!r}")

    if context.active_object and context.active_object.type == "ARMATURE":
        stan_debug(
            operator,
            f"  active object: {context.active_object.name!r} (type={context.active_object.type})",
        )
        if context.active_object.name.lower().startswith(stem_lower):
            stan_debug(operator, f"  matched active armature: {context.active_object.name!r}")
            return context.active_object

    for obj in context.scene.objects:
        if obj.type == "ARMATURE":
            stan_debug(operator, f"  scene armature: {obj.name!r}")
            if obj.name.lower().startswith(stem_lower):
                stan_debug(operator, f"  matched scene armature: {obj.name!r}")
                return obj

    for coll in context.scene.collection.children_recursive:
        if coll.name != "Equipment Models":
            continue
        stan_debug(operator, f"  searching Equipment Models collection")
        for obj in coll.objects:
            if obj.type == "ARMATURE":
                stan_debug(operator, f"    equipment armature: {obj.name!r}")
                if obj.name.lower().startswith(stem_lower):
                    stan_debug(operator, f"    matched equipment armature: {obj.name!r}")
                    return obj
        for child in coll.children:
            for obj in child.objects:
                if obj.type == "ARMATURE":
                    stan_debug(operator, f"    equipment child armature: {obj.name!r}")
                    if obj.name.lower().startswith(stem_lower):
                        stan_debug(operator, f"    matched equipment child armature: {obj.name!r}")
                        return obj

    stan_debug(operator, f"No armature found for {weapon_stem!r}")
    return None
