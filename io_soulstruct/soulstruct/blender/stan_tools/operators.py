from __future__ import annotations

__all__ = [
    "AutoDetectGameDirectory",
    "StanRefreshNpcParamList",
    "StanRefreshC0000SubAnibndList",
    "StanApplyNpcParamDrawMask",
    "StanShowAllCharacterMeshes",
    "StanApplySceneLighting",
    "StanRemoveSceneLighting",
    "StanTextTooltip",
    "text_with_tooltip",
]

from pathlib import Path

import bpy

from ..general.properties import SoulstructSettings
from ..base.operators import LoggingOperator
from soulstruct.games import NIGHTREIGN

from .regulation_bin import auto_set_regulation_bin_dir
from .steam_paths import detect_game_root
from .mesh_mask_visibility import show_all_character_meshes
from .npc_param import find_character_armature, _resolve_npc_param_xml_path
from .scene_lighting import apply_scene_lighting, remove_scene_lighting
from ..base.register import io_soulstruct_operator


@io_soulstruct_operator
class AutoDetectGameDirectory(LoggingOperator):
    """Find the game install via Steam and set Game Root (+ default Mod Folder)."""

    bl_idname = "stan_tools.auto_detect_game_dir"
    bl_label = "Auto-Detect Game Directory"
    bl_description = (
        "Scan Steam library folders for the selected game's install and set Game Root. "
        "If Mod Folder is empty, defaults to <Game Root>/mod"
    )

    def execute(self, context):
        settings = SoulstructSettings.from_context(context)
        game = settings.game
        if not game:
            return self.error("Select a game first.")

        root = detect_game_root(game.variable_name)
        if root is None:
            return self.warning(
                f"Could not find {game.name} under Steam libraries. Set Game Root manually."
            )

        prop_name = settings.get_game_root_prop_name()
        setattr(settings.game_settings, prop_name, str(root))
        settings.auto_set_game()
        self.info(f"Set game root: {root}")

        mod_prop = settings.get_mod_root_prop_name()
        if not getattr(settings.game_settings, mod_prop, ""):
            mod_path = root / "mod"
            setattr(settings.game_settings, mod_prop, str(mod_path))
            self.info(f"Set mod folder: {mod_path}")

        if settings.is_game(NIGHTREIGN) and not settings.nightreign_unpack_staging_str:
            decrypted = Path(r"S:\_modding\tools\soulstruct-blender\_tmp\nr-full-unpack-decrypted")
            staging = Path(r"S:\_modding\tools\soulstruct-blender\_tmp\nr-full-unpack")
            default_staging = decrypted if decrypted.is_dir() else staging
            if default_staging.is_dir():
                settings.nightreign_unpack_staging_str = str(default_staging)
                self.info(f"Set unpack staging: {default_staging}")

        stan = context.scene.stan_tools_settings
        reg_dir = auto_set_regulation_bin_dir(stan, settings)
        from .remembered_folders import remember_folders

        remember_folders(context)
        if reg_dir:
            self.info(f"Set regulation-bin: {reg_dir}")

        return {"FINISHED"}


@io_soulstruct_operator
class StanRefreshC0000SubAnibndList(LoggingOperator):
    """Reload c0000 sub-ANIBND choices from c0000.anibnd."""

    bl_idname = "stan_tools.refresh_c0000_sub_anibnd_list"
    bl_label = "Refresh c0000 Sub-ANIBND List"
    bl_description = "Reload c0000 sub-ANIBND binders registered in c0000.anibnd"

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        if stan.refresh_c0000_sub_anibnd_list(context):
            self.info("Loaded c0000 sub-ANIBND list.")
            return {"FINISHED"}
        return self.warning(
            "c0000.anibnd not found. Set Game Root with unpacked chr/c0000.anibnd for weapon attack preview."
        )


@io_soulstruct_operator
class StanRefreshNpcParamList(LoggingOperator):
    """Reload NpcParam rows for the active character from NpcParam.param.xml."""

    bl_idname = "stan_tools.refresh_npc_param_list"
    bl_label = "Refresh NPC Param List"
    bl_description = "Reload NpcParam variants for the selected character from NpcParam.param.xml"

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        settings = SoulstructSettings.from_context(context)
        if stan.refresh_npc_param_list(context):
            self.info(f"Loaded NPC Param rows for {stan.character_model}.")
            return {"FINISHED"}
        if not stan.character_model:
            return self.warning("Import a character (c####) first.")
        if not _resolve_npc_param_xml_path(settings, stan):
            return self.warning(
                "NpcParam.param.xml not found. Click Unpack Nightreign Files in Setup to create it from your game."
            )
        return self.warning(f"NpcParam has no rows for {stan.character_model}.")


@io_soulstruct_operator
class StanApplyNpcParamDrawMask(LoggingOperator):
    """Apply the selected NpcParam draw mask to character mesh visibility."""

    bl_idname = "stan_tools.apply_npc_param_draw_mask"
    bl_label = "Apply NPC Param Visibility"
    bl_description = "Show/hide FLVER mesh parts using the selected NpcParam model display masks"

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        err = stan.apply_active_npc_param(context)
        if err:
            return self.warning(err)
        armature = find_character_armature(context, stan.character_model)
        if armature and armature.get("stan_mesh_mask_split"):
            self.info("Updated mesh visibility (split by material / display mask).")
        else:
            self.info("Updated mesh visibility from NPC Param draw mask.")
        return {"FINISHED"}


@io_soulstruct_operator
class StanShowAllCharacterMeshes(LoggingOperator):
    """Show all mesh children of the active character (ignore draw masks)."""

    bl_idname = "stan_tools.show_all_character_meshes"
    bl_label = "Show All Meshes"
    bl_description = "Unhide every mesh part of the active character armature"

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        if not stan.character_model:
            return self.warning("No active character. Import one first.")
        armature = find_character_armature(context, stan.character_model)
        if armature is None:
            return self.warning(f"Armature not found for {stan.character_model}.")
        count = show_all_character_meshes(armature)
        self.info(f"Showing {count} mesh object(s).")
        return {"FINISHED"}


@io_soulstruct_operator
class StanApplySceneLighting(LoggingOperator):
    """Add or update 3-point viewport lighting and world sky/HDRI."""

    bl_idname = "stan_tools.apply_scene_lighting"
    bl_label = "Apply Scene Lighting"
    bl_description = (
        "Create StanTools 3-point area lights and world environment for Material Preview / Rendered view"
    )

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        _light_count, message = apply_scene_lighting(context, stan)
        self.info(message)
        return {"FINISHED"}


@io_soulstruct_operator
class StanRemoveSceneLighting(LoggingOperator):
    """Remove StanTools viewport lighting and reset world to a dark studio."""

    bl_idname = "stan_tools.remove_scene_lighting"
    bl_label = "Remove Scene Lighting"
    bl_description = "Delete StanTools lights and restore a simple dark world background"

    def execute(self, context):
        remove_scene_lighting(context)
        self.info("Scene lighting removed.")
        return {"FINISHED"}

@io_soulstruct_operator
class StanTextTooltip(bpy.types.Operator):
    """Flat 'label' whose tooltip shows the full text (Blender labels have no tooltips). Click copies it."""

    bl_idname = "stan_tools.text_tooltip"
    bl_label = ""
    bl_options = {"INTERNAL"}

    text: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        return f"{properties.text}\n\nClick to copy"

    def execute(self, context):
        context.window_manager.clipboard = self.text
        return {"FINISHED"}


def text_with_tooltip(layout: bpy.types.UILayout, text: str, full_text: str = "", icon: str = "NONE"):
    """Draw `text` like a label, with `full_text` (default: `text`) on hover for when the panel truncates it."""
    op = layout.operator(StanTextTooltip.bl_idname, text=text, icon=icon, emboss=False)
    op.text = full_text or text
