"""Resolve active character armature/model for Stan's Tools operators."""
from __future__ import annotations

import bpy

from ..animation.utilities import get_active_flver_or_part_armature

from .npc_param import find_character_armature


def resolve_stan_character_context(
    context: bpy.types.Context,
) -> tuple[bpy.types.Object | None, bpy.types.Object | None, str]:
    """Return (armature, mesh, model_stem) for Stan's Tools character workflows.

    Uses the active FLVER selection when possible, otherwise the last imported
    character from Stan's Tools settings.
    """
    armature_obj, mesh_obj, model_name, is_part = get_active_flver_or_part_armature(context)
    if armature_obj and model_name.startswith("c") and not is_part:
        return armature_obj, mesh_obj, model_name[:5].lower() if len(model_name) >= 5 else model_name.lower()

    stan = context.scene.stan_tools_settings
    if stan.character_model:
        armature = find_character_armature(context, stan.character_model)
        if armature:
            return armature, None, stan.character_model

    return None, None, ""
