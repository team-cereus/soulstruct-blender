"""DSAS-style persistent player character (c0000 + armor) for weapon testing."""

from __future__ import annotations

import bpy

from soulstruct.blender.utilities import LoggingOperator, find_or_create_collection

from .debug_log import stan_debug, stan_info, stan_warning
from .equipment_assembly import assemble_er_preview_after_import, find_c0000_armature
from .weapon_preview_body import (
    _iter_parts_directories,
    get_er_preview_part_stems,
    import_ds1_preview_body,
    import_er_preview_body,
)

__all__ = [
    "PLAYER_CHARACTER_STEM",
    "PLAYER_COLLECTION",
    "load_player_character",
    "is_player_character_loaded",
    "clear_player_character",
    "StanLoadPlayerCharacter",
]

PLAYER_CHARACTER_STEM = "c0000"
PLAYER_COLLECTION = "Player Character"

_GENDER_ITEMS = [
    ("MALE", "Male", "DSAS default male c0000 + armor parts"),
    ("FEMALE", "Female", "DSAS default female c0000 + armor parts"),
]


def _move_objects_to_player_collection(
    context: bpy.types.Context,
    object_names: set[str],
) -> None:
    """Link imported objects into the Player Character collection."""
    if not object_names:
        return
    collection = find_or_create_collection(context.scene.collection, PLAYER_COLLECTION)
    for name in object_names:
        obj = context.scene.objects.get(name)
        if obj is None:
            continue
        for coll in obj.users_collection:
            coll.objects.unlink(obj)
        collection.objects.link(obj)


def _snapshot_object_names(context: bpy.types.Context) -> set[str]:
    return {obj.name for obj in context.scene.objects}


def load_player_character(
    operator,
    context: bpy.types.Context,
    settings,
    stan,
    *,
    female: bool,
) -> set[str]:
    """Import c0000 + armor parts, glue like DSAS, move to Player Character collection."""
    before = _snapshot_object_names(context)
    gender_label = "female" if female else "male"
    stan_debug(operator, f"Loading DSAS player character ({gender_label})")

    if settings.is_er_family():
        part_stems = get_er_preview_part_stems(settings, stan, female=female)
        result = import_er_preview_body(
            operator,
            context,
            settings,
            female=female,
            part_stems=part_stems,
        )
        if result == {"CANCELLED"}:
            return result
        assemble_er_preview_after_import(context, operator=operator, part_stems=part_stems)
    else:
        parts_dirs = _iter_parts_directories(settings)
        result = import_ds1_preview_body(
            operator,
            context,
            settings,
            female=female,
            disk_stems=None,
        )
        if result == {"CANCELLED"}:
            return result

    after = _snapshot_object_names(context)
    new_names = after - before
    _move_objects_to_player_collection(context, new_names)

    if find_c0000_armature(context) is None:
        stan_warning(operator, "Player character import finished but c0000 armature not found.")
        if operator is not None:
            operator.error("c0000 armature not found after import.")
        return {"CANCELLED"}

    stan.player_character_loaded = True
    stan.player_character_gender = "FEMALE" if female else "MALE"
    stan.character_model = PLAYER_CHARACTER_STEM
    stan.refresh_npc_param_list(context, model_stem=PLAYER_CHARACTER_STEM)
    stan.refresh_c0000_sub_anibnd_list(context)

    stan_info(operator, f"Loaded player character c0000 ({gender_label}). Equip weapons from Weapons tab.")
    return {"FINISHED"}


def is_player_character_loaded(context: bpy.types.Context) -> bool:
    """True when stan flag is set and c0000 armature exists in scene."""
    stan = context.scene.stan_tools_settings
    if not stan.player_character_loaded:
        return False
    return find_c0000_armature(context) is not None


def clear_player_character(context: bpy.types.Context) -> int:
    """Remove objects in Player Character collection. Returns count removed."""
    stan = context.scene.stan_tools_settings
    removed = 0
    coll = bpy.data.collections.get(PLAYER_COLLECTION)
    if coll is not None:
        for obj in list(coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        bpy.data.collections.remove(coll)
    stan.player_character_loaded = False
    stan.character_model = ""
    return removed


class StanLoadPlayerCharacter(LoggingOperator):
    """Load c0000 skeleton + LG/BD/AM/HD armor glued like DSAS."""

    bl_idname = "stan_tools.load_player_character"
    bl_label = "Load Player Character (DSAS)"
    bl_description = (
        "Import c0000 skeleton + LG/BD/AM/HD armor parts (DirectBoneMap) like DSAS for weapon testing"
    )
    bl_options = {"REGISTER", "UNDO"}

    gender: bpy.props.EnumProperty(
        name="Gender",
        items=_GENDER_ITEMS,
        default="MALE",
    )

    @classmethod
    def poll(cls, context) -> bool:
        from soulstruct.blender.general.properties import SoulstructSettings

        settings = SoulstructSettings.from_context(context)
        return settings.has_import_dir_path("chr") and settings.has_import_dir_path("parts")

    def invoke(self, context, event):
        stan = context.scene.stan_tools_settings
        self.gender = stan.player_character_gender
        return self.execute(context)

    def execute(self, context):
        settings = context.scene.soulstruct_settings
        stan = context.scene.stan_tools_settings
        stan.player_character_gender = self.gender
        female = self.gender == "FEMALE"
        return load_player_character(self, context, settings, stan, female=female)
