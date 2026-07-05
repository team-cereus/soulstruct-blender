"""Weapon search/import helpers for Stan's Tools."""

from __future__ import annotations

__all__ = [
    "StanSearchWeaponToImport",
    "build_weapon_search_items",
    "_iter_parts_directories",
]

import re
from pathlib import Path

import bpy

from soulstruct.blender.flver.models.operators.import_operators import ImportEquipmentFLVER
from soulstruct.blender.general.weapon_names import get_weapon_index

from .debug_log import stan_debug, stan_info, stan_warning
from .equip_weapon_param import get_weapon_row
from .player_character import is_player_character_loaded
from .unequip_weapon import unequip_active_weapon
from .weapon_attach import attach_weapon_to_player
from .weapon_import import import_weapon_partsbnd
from .weapon_preview_body import _iter_parts_directories

_PARTS_BND_RE = re.compile(r"^(WP_A_\d{4})\.partsbnd(\.dcx)?(\.bak)?$", re.IGNORECASE)


def _parts_stems_on_disk(parts_dirs: list[Path]) -> dict[str, Path]:
    """Map lowercase WP_A_#### stem -> first matching PARTSBND path."""
    stems: dict[str, Path] = {}
    for parts_dir in parts_dirs:
        for path in sorted(parts_dir.iterdir()):
            match = _PARTS_BND_RE.match(path.name)
            if not match:
                continue
            stem = match.group(1).upper()
            stems.setdefault(stem.lower(), path)
    return stems


def build_weapon_search_items(context: bpy.types.Context) -> list[tuple[str, str, str]]:
    settings = context.scene.soulstruct_settings
    parts_dirs = _iter_parts_directories(settings)

    if not settings.game_root_path and not settings.project_root_path:
        return [("", "<set Game Root in Stan's Tools / Setup>", "")]

    if not parts_dirs:
        game = settings.game_root_path or "(not set)"
        project = settings.project_root_path or "(not set)"
        return [
            (
                "",
                f"<no parts/ folder — Game: {game} | Project: {project}>",
                "Unpack game files so Game/parts exists",
            )
        ]

    index = get_weapon_index(settings)
    disk_stems = _parts_stems_on_disk(parts_dirs)
    items: list[tuple[str, str, str]] = []
    seen_rows: set[int] = set()

    for row_id, entry in sorted(index.items()):
        stem = entry.get("stem", "")
        if not stem:
            continue
        if stem.lower() not in disk_stems:
            continue
        name = entry.get("name", stem)
        label = f"{row_id} - {name} ({stem})"
        items.append((str(row_id), label, label))
        seen_rows.add(row_id)

    for stem_lower, _path in sorted(disk_stems.items()):
        stem = stem_lower.upper()
        if any(e.get("stem", "").lower() == stem_lower for e in index.values()):
            continue
        try:
            equip_id = int(stem[5:9])
        except ValueError:
            continue
        if settings.is_er_family():
            row_id = equip_id * 10000
        else:
            row_id = equip_id * 1000
        if row_id in seen_rows:
            continue
        label = f"{row_id} - {stem}"
        items.append((str(row_id), label, label))
        seen_rows.add(row_id)

    if not items:
        roots = ", ".join(str(d) for d in parts_dirs)
        return [("", f"<no indexed WP_A_####.partsbnd in parts/ at {roots}>", "")]

    return items


class StanSearchWeaponToImport(ImportEquipmentFLVER):
    """Import weapon FLVER by EquipParamWeapon row id (Stan's Tools)."""

    bl_idname = "stan_tools.search_weapon"
    bl_label = "Search Weapon by Name"
    bl_description = (
        "Search weapons in game/project parts\\ by EquipParamWeapon row id or name, "
        "then equip on the loaded player character (does not reload c0000)"
    )
    bl_options = {"REGISTER", "UNDO"}

    bl_property = "weapon_row"

    _search_items: list[tuple[str, str, str]] = [("", "", "")]

    def _weapon_enum_items(self, context):
        return StanSearchWeaponToImport._search_items

    weapon_row: bpy.props.EnumProperty(
        name="Weapon",
        description="EquipParamWeapon row to import",
        items=_weapon_enum_items,
    )

    @classmethod
    def poll(cls, context) -> bool:
        settings = cls.settings(context)
        return (
            settings.has_import_dir_path("parts")
            and is_player_character_loaded(context)
        )

    def invoke(self, context, event):
        StanSearchWeaponToImport._search_items = build_weapon_search_items(context)
        if len(StanSearchWeaponToImport._search_items) == 1 and not StanSearchWeaponToImport._search_items[0][0]:
            return self.error(StanSearchWeaponToImport._search_items[0][1])
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.weapon_row:
            return self.error("No weapon selected.")

        if not is_player_character_loaded(context):
            return self.error("Load player character first (Characters tab → Load Player Character).")

        try:
            row_id = int(self.weapon_row)
        except ValueError:
            return self.error("Invalid weapon row id.")

        settings = self.settings(context)
        stan = context.scene.stan_tools_settings
        weapon = get_weapon_row(settings, stan, row_id)
        if weapon is None or not weapon.stem:
            return self.error(f"No weapon metadata for row {row_id}.")

        stan_debug(
            self,
            f"Equip weapon row {row_id}: stem={weapon.stem}, name={weapon.name!r}, "
            f"absorpParamId={weapon.absorp_param_id}",
        )

        parts_dirs = _iter_parts_directories(settings)
        disk_stems = _parts_stems_on_disk(parts_dirs)
        parts_path = disk_stems.get(weapon.stem.lower())
        if parts_path is None:
            return self.error(f"PARTSBND not found for {weapon.stem} under parts/.")

        stan_debug(self, f"Weapon PARTSBND path: {parts_path}")

        unequip_active_weapon(context, operator=self)

        stan_debug(self, f"Importing weapon PARTSBND: {parts_path}")
        result = import_weapon_partsbnd(self, context, parts_path)
        if result != {"FINISHED"}:
            stan_warning(self, f"Weapon import returned {result!r} for {parts_path}")
            return result

        if not attach_weapon_to_player(context, weapon, weapon.stem, settings, stan, operator=self):
            stan_warning(self, f"Weapon imported but hand attachment failed for {weapon.stem}.")

        stan.weapon_row_id = str(row_id)
        stan.weapon_stem = weapon.stem
        stan.refresh_c0000_sub_anibnd_list(context)

        stan_info(
            self,
            f"Equipped {weapon.stem} ({weapon.name}) on player c0000. Load attack animations below.",
        )
        return {"FINISHED"}
