from __future__ import annotations

__all__ = [
    "StanSetupPanel",
    "StanCharactersPanel",
    "StanWeaponsPanel",
    "StanAnimationPanel",
    "StanViewportPanel",
]

from pathlib import Path

import bpy

from soulstruct.blender.bpy_base.panel import SoulstructPanel
from soulstruct.blender.general.properties import SoulstructSettings
from soulstruct.blender.stan_tools.character_search import _iter_chr_directories
from soulstruct.blender.animation.export_operators import ExportCharacterHKXAnimation

from .character_search import StanSearchCharacterToImport
from .animation_search import StanSearchCharacterAnimation
from .weapon_search import StanSearchWeaponToImport, _iter_parts_directories
from .weapon_anim import StanLoadWeaponAttackAnimation
from .player_character import StanLoadPlayerCharacter, is_player_character_loaded
from .operators import (
    AutoDetectGameDirectory,
    StanRefreshNpcParamList,
    StanRefreshC0000SubAnibndList,
    StanApplyNpcParamDrawMask,
    StanShowAllCharacterMeshes,
    StanApplySceneLighting,
    StanRemoveSceneLighting,
)
from .npc_param import _resolve_npc_param_xml_path
from .equip_weapon_param import resolve_equip_weapon_xml_path
from .scene_lighting import is_scene_lighting_active

STAN_TOOLS_CATEGORY = "Stan's Tools"


class _StanToolsPanel(SoulstructPanel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = STAN_TOOLS_CATEGORY


class StanSetupPanel(_StanToolsPanel):
    bl_label = "Setup"
    bl_idname = "VIEW_PT_stan_tools_setup"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.soulstruct_settings
        export_settings = context.scene.animation_export_settings

        layout.label(text="Game & folders for animation modding", icon="INFO")

        layout.prop(settings, "game_enum")
        game = settings.game
        if not game:
            layout.label(text="Unsupported game.", icon="ERROR")
            return

        row = layout.row(align=True)
        row.label(text="Game Root:")
        row.operator(AutoDetectGameDirectory.bl_idname, text="", icon="VIEWZOOM")
        layout.prop(settings, settings.get_game_root_prop_name(), text="")

        layout.label(text="Project Root (optional export workspace):")
        layout.prop(settings, settings.get_project_root_prop_name(), text="")

        layout.label(text="Mod Folder (DSAS / ModEngine):")
        layout.prop(settings, settings.get_mod_root_prop_name(), text="")

        layout.prop(settings, "prefer_import_from_project")
        layout.prop(export_settings, "auto_repack_to_mod")

        stan = context.scene.stan_tools_settings
        layout.label(text="NpcParam (mesh visibility states):")
        layout.prop(stan, "npc_param_xml_path", text="")
        xml_path = _resolve_npc_param_xml_path(settings, stan)
        if xml_path:
            layout.label(text=f"Using: {xml_path.name}", icon="CHECKMARK")
        elif stan.npc_param_xml_path or settings.project_root_path:
            layout.label(text="NpcParam.param.xml not found", icon="ERROR")

        layout.label(text="EquipParamWeapon (weapon attacks):")
        layout.prop(stan, "equip_weapon_param_xml_path", text="")
        weapon_xml = resolve_equip_weapon_xml_path(settings, stan)
        if weapon_xml:
            layout.label(text=f"Using: {weapon_xml.name}", icon="CHECKMARK")

        chr_dirs = _iter_chr_directories(settings)
        if chr_dirs:
            count = sum(1 for d in chr_dirs for _ in d.glob("c*.chrbnd*"))
            layout.label(text=f"chr\\ found: {count} binder(s) in {len(chr_dirs)} folder(s)", icon="CHECKMARK")
        elif settings.game_root_path or settings.project_root_path:
            layout.label(text="chr\\ missing — set Game Root to unpacked .../Game", icon="ERROR")
        else:
            layout.label(text="Set Game Root or use Auto-Detect", icon="ERROR")


class StanCharactersPanel(_StanToolsPanel):
    bl_label = "Characters"
    bl_idname = "VIEW_PT_stan_tools_characters"

    @classmethod
    def poll(cls, context):
        return SoulstructSettings.from_context(context).has_import_dir_path("chr")

    def draw(self, context):
        layout = self.layout
        stan = context.scene.stan_tools_settings

        box = layout.box()
        box.label(text="Player Character (weapon testing)", icon="USER")
        row = box.row(align=True)
        row.prop(stan, "player_character_gender", text="")
        row.operator(StanLoadPlayerCharacter.bl_idname, icon="IMPORT")
        if is_player_character_loaded(context):
            gender = stan.player_character_gender.lower()
            box.label(text=f"Player c0000 loaded ({gender})", icon="CHECKMARK")
        else:
            box.label(text="Not loaded — required for Weapons tab", icon="ERROR")
        box.label(text="Load once; equipping weapons does not reload the body")

        layout.separator()
        layout.label(text="Search by name or c#### id, then import the model")
        layout.operator(StanSearchCharacterToImport.bl_idname, icon="VIEWZOOM")
        layout.label(text="Load animation (uses last imported c####):")
        layout.operator(StanSearchCharacterAnimation.bl_idname, icon="ANIM")

        box = layout.box()
        box.label(text="NPC Param Selection (mesh visibility)", icon="MODIFIER")
        if stan.character_model:
            box.label(text=f"Character: {stan.character_model}")
        row = box.row(align=True)
        row.prop(stan, "npc_param_row_id", text="")
        row.operator(StanRefreshNpcParamList.bl_idname, text="", icon="FILE_REFRESH")
        row = box.row(align=True)
        row.operator(StanApplyNpcParamDrawMask.bl_idname, icon="HIDE_OFF")
        row.operator(StanShowAllCharacterMeshes.bl_idname, icon="RESTRICT_VIEW_OFF")
        box.label(text="NPC Param applies on selection; Apply re-runs if needed")


class StanWeaponsPanel(_StanToolsPanel):
    bl_label = "Weapons"
    bl_idname = "VIEW_PT_stan_tools_weapons"

    @classmethod
    def poll(cls, context):
        from soulstruct.blender.general.properties import SoulstructSettings

        settings = SoulstructSettings.from_context(context)
        return settings.has_import_dir_path("parts") and is_player_character_loaded(context)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.soulstruct_settings
        stan = context.scene.stan_tools_settings

        if is_player_character_loaded(context):
            layout.label(text=f"Player: c0000 ({stan.player_character_gender.lower()}) ready", icon="CHECKMARK")
        else:
            layout.label(text="Load player character in Characters tab first", icon="ERROR")
            return

        layout.label(text="Search by EquipParamWeapon row id or name")
        layout.operator(StanSearchWeaponToImport.bl_idname, icon="VIEWZOOM")

        layout.label(text="EquipParamWeapon (wepmotionCategory):")
        layout.prop(stan, "equip_weapon_param_xml_path", text="")
        xml_path = resolve_equip_weapon_xml_path(settings, stan)
        if xml_path:
            layout.label(text=f"Using: {xml_path.name}", icon="CHECKMARK")
        elif stan.equip_weapon_param_xml_path or settings.project_root_path:
            layout.label(text="EquipParamWeapon.param.xml not found", icon="ERROR")

        if stan.weapon_stem:
            layout.label(text=f"Active weapon: {stan.weapon_stem}", icon="OUTLINER_OB_ARMATURE")
            if stan.weapon_row_id:
                layout.label(text=f"Row id: {stan.weapon_row_id}")

        box = layout.box()
        box.label(text="c0000 attack animations", icon="ANIM")
        row = box.row(align=True)
        row.prop(stan, "c0000_sub_anibnd", text="")
        row.operator(StanRefreshC0000SubAnibndList.bl_idname, text="", icon="FILE_REFRESH")
        box.prop(stan, "weapon_attack_slot", text="Attack Slot")
        box.operator(StanLoadWeaponAttackAnimation.bl_idname, text="Load Weapon Attack", icon="ANIM")

        parts_dirs = _iter_parts_directories(settings)
        if parts_dirs:
            count = sum(1 for d in parts_dirs for _ in d.glob("WP_A_*.partsbnd*"))
            layout.label(text=f"parts\\ found: {count} weapon binder(s)", icon="CHECKMARK")


class StanAnimationPanel(_StanToolsPanel):
    bl_label = "Animation"
    bl_idname = "VIEW_PT_stan_tools_animation"

    @classmethod
    def poll(cls, context):
        return SoulstructSettings.from_context(context).game_config.supports_animation

    def draw(self, context):
        layout = self.layout
        settings = context.scene.soulstruct_settings
        export_settings = context.scene.animation_export_settings

        if not settings.game_config.supports_animation:
            layout.label(text="Animation not supported for this game.")
            return

        layout.prop(export_settings, "selected_frames_only")
        layout.label(text="Export active action on selected character armature:")
        self.maybe_draw_export_operator(
            context,
            ExportCharacterHKXAnimation.bl_idname,
            text="Export Character Animation",
            icon="EXPORT",
        )
        if settings.mod_root_path:
            layout.label(text=f"Mod copy: {settings.mod_root_path / 'chr'}", icon="FILE_FOLDER")
        elif export_settings.auto_repack_to_mod:
            layout.label(text="Set Mod Folder in Setup to auto-copy ANIBND", icon="ERROR")


class StanViewportPanel(_StanToolsPanel):
    bl_label = "Viewport"
    bl_idname = "VIEW_PT_stan_tools_viewport"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        stan = context.scene.stan_tools_settings

        layout.label(
            text="3-point lights + world sky for Material Preview / Rendered",
            icon="LIGHT_SUN",
        )

        layout.prop(stan, "scene_lighting_sky_strength")
        layout.prop(stan, "scene_lighting_key_energy")
        layout.prop(stan, "scene_lighting_fill_energy")
        layout.prop(stan, "scene_lighting_rim_energy")
        layout.prop(stan, "scene_lighting_hdri_path", text="HDRI")

        row = layout.row(align=True)
        row.operator(StanApplySceneLighting.bl_idname, icon="LIGHT_AREA")
        row.operator(StanRemoveSceneLighting.bl_idname, icon="TRASH")

        if is_scene_lighting_active():
            layout.label(text="Scene lighting: ON", icon="CHECKMARK")
        else:
            layout.label(text="Scene lighting: OFF", icon="BLANK1")
