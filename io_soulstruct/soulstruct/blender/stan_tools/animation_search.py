"""Searchable character animation import for Stan's Tools."""
from __future__ import annotations

__all__ = [
    "StanSearchCharacterAnimation",
    "build_character_animation_search_items",
]

import re

import bpy

from soulstruct.containers import BinderEntry

from ..animation.import_operators import ImportHKXAnimationWithBinderChoice
from ..animation.utilities import (
    import_character_hkx_animation_entry,
    load_character_anibnd_bundle,
)
from ..base.operators import LoggingOperator
from .list_picker import ListPickerMixin

from .animation_labels import label_for_animation_entry, load_tae_labels_for_binder
from .character_context import resolve_stan_character_context
from ..base.register import io_soulstruct_operator

_HKX_ENTRY_RE = re.compile(r"^a.*\.hkx(\.dcx)?$", re.IGNORECASE)


def build_character_animation_search_items(
    context: bpy.types.Context,
) -> list[tuple[str, str, str]]:
    armature_obj, _, model_name = resolve_stan_character_context(context)
    if armature_obj is None or not model_name:
        return [("", "<import a character first>", "Use Search Character by Name")]

    settings = context.scene.soulstruct_settings
    try:
        anibnd, _, _ = load_character_anibnd_bundle(settings, model_name)
    except Exception as ex:
        return [("", f"<{ex}>", "")]

    if model_name == "c0000":
        return [
            (
                "",
                "<use Animation panel Import Character Anim for c0000>",
                "Player skeleton uses sub-ANIBND picker",
            )
        ]

    tae_labels = load_tae_labels_for_binder(anibnd)
    entries = [e for e in anibnd.entries if _HKX_ENTRY_RE.match(e.name)]
    if not entries:
        return [("", f"<no animations in {anibnd.path_name}>", "")]

    items: list[tuple[str, str, str]] = []
    for entry in sorted(entries, key=lambda e: e.name):
        label = label_for_animation_entry(entry, tae_labels)
        items.append((str(entry.entry_id), label, f"Import {entry.name} from {model_name} ANIBND"))
    return items


@io_soulstruct_operator
class StanSearchCharacterAnimation(ListPickerMixin, LoggingOperator):
    """Import one HKX clip from the active character's ANIBND via search popup."""

    bl_idname = "stan_tools.search_character_animation"
    bl_label = "Load Character Animation"
    bl_description = (
        "Search animations in the selected character's ANIBND (by clip id). "
        "Uses the last character imported via Stan's Tools if none is selected"
    )
    bl_options = {"REGISTER", "UNDO"}

    _search_items: list[tuple[str, str, str]] = [("", "", "")]

    def _animation_enum_items(self, context):
        return StanSearchCharacterAnimation._search_items

    animation_entry_id: bpy.props.EnumProperty(
        name="Animation",
        description="HKX animation entry to import",
        items=_animation_enum_items,
    )

    @classmethod
    def poll(cls, context) -> bool:
        if not context.scene.soulstruct_settings.game_config.supports_animation:
            return False
        armature_obj, _, model_name = resolve_stan_character_context(context)
        return armature_obj is not None and model_name.startswith("c") and model_name != "c0000"

    def invoke(self, context, event):
        StanSearchCharacterAnimation._search_items = build_character_animation_search_items(context)
        if (
            len(StanSearchCharacterAnimation._search_items) == 1
            and not StanSearchCharacterAnimation._search_items[0][0]
        ):
            return self.error(StanSearchCharacterAnimation._search_items[0][1])
        return self.open_picker(context, StanSearchCharacterAnimation._search_items)

    def execute(self, context):
        self.animation_entry_id = self.picked(context, self.animation_entry_id)
        if not self.animation_entry_id:
            return self.error("No animation selected.")

        try:
            entry_id = int(self.animation_entry_id)
        except ValueError:
            return self.error("Invalid animation entry id.")

        armature_obj, mesh_obj, model_name = resolve_stan_character_context(context)
        if armature_obj is None or not model_name.startswith("c"):
            return self.error("Import a character first (Search Character by Name).")

        settings = self.settings(context)
        try:
            anibnd, skeleton_hkx, compendium = load_character_anibnd_bundle(settings, model_name)
        except Exception as ex:
            return self.error(str(ex))

        try:
            entry = anibnd[entry_id]
        except (KeyError, TypeError):
            return self.error(f"Animation entry id {entry_id} not found in ANIBND.")

        if not _HKX_ENTRY_RE.match(entry.name):
            return self.error(f"Entry is not an HKX animation: {entry.name}")

        ImportHKXAnimationWithBinderChoice.BINDER = anibnd
        ImportHKXAnimationWithBinderChoice.ARMATURE_OBJ = armature_obj
        ImportHKXAnimationWithBinderChoice.PART_MESH_OBJ = mesh_obj
        ImportHKXAnimationWithBinderChoice.MODEL_NAME = model_name
        ImportHKXAnimationWithBinderChoice.SKELETON_HKX = skeleton_hkx
        ImportHKXAnimationWithBinderChoice.HKX_COMPENDIUM = compendium

        return import_character_hkx_animation_entry(
            self,
            context,
            entry=entry,
            binder=anibnd,
            armature_obj=armature_obj,
            part_mesh_obj=mesh_obj,
            model_name=model_name,
            skeleton_hkx=skeleton_hkx,
            compendium=compendium,
        )
