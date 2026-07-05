"""Load c0000 weapon attack animations onto imported weapon armatures."""

from __future__ import annotations

__all__ = [
    "StanLoadWeaponAttackAnimation",
    "list_c0000_sub_anibnd_stems",
    "find_attack_animation_entry",
]

import re
from pathlib import Path

import bpy

from soulstruct.containers import BinderEntry
from soulstruct.eldenring.containers import DivBinder

from soulstruct.blender.animation.import_operators import ImportHKXAnimationWithBinderChoice
from soulstruct.blender.animation.types import SoulstructAnimation
from soulstruct.blender.animation.utilities import (
    import_character_hkx_animation_entry,
    load_character_anibnd_bundle,
)
from soulstruct.blender.utilities import LoggingOperator

from .debug_log import stan_debug, stan_info, stan_warning
from .equip_weapon_param import get_weapon_row
from .equipment_assembly import find_c0000_armature
from .player_character import is_player_character_loaded
from .weapon_attack_slots import (
    ATTACK_SLOTS,
    anim_id_to_binder_entry_id,
    attack_hkx_stem,
    get_attack_slot,
)

_HKX_ENTRY_RE = re.compile(r"^a.*\.hkx(\.dcx)?$", re.IGNORECASE)


# ER/NR player attack clips live in the base c0000 ANIBND plus separate DLC expansion binders
# (e.g. Backhand Blade animations are in c0000_dlc02.anibnd). These are real files on disk; the
# `c0000_*.txt` entries *inside* c0000.anibnd are internal animation lists, NOT loadable binders.
_C0000_ATTACK_ANIBND_STEMS = ("c0000", "c0000_dlc01", "c0000_dlc02")


def _resolve_anibnd_path(settings, stem: str):
    """Resolve ``chr/{stem}.anibnd[.dcx]`` in project or game dir; return None if absent.

    `settings.get_import_file_path` RAISES `FileNotFoundError` when missing (it does not return
    None), so callers must not assume a falsy return — we translate that into None here.
    """
    try:
        game_anim_info = SoulstructAnimation.GAME_ANIMATION_INFO_CHR[settings.game]
    except KeyError:
        return None
    relative_path = Path(game_anim_info.relative_binder_path.format(model_name=stem))
    try:
        path = settings.get_import_file_path(relative_path)
    except FileNotFoundError:
        return None
    if path and path.is_file():
        return path
    return None


def list_c0000_sub_anibnd_stems(settings) -> list[str]:
    """Return c0000 attack ANIBND stems that actually exist on disk (base + DLC binders).

    The base ``c0000.anibnd`` is a `DivBinder` whose divisions are merged transparently, so it
    already exposes all base-game attack clips. DLC clips require their separate expansion binders.
    """
    stems: list[str] = []

    base_path = _resolve_anibnd_path(settings, "c0000")
    if base_path is not None:
        stems.append("c0000")
        # Discover sibling DLC/expansion binders next to the base file (whichever root it came from).
        for sibling in sorted(base_path.parent.glob("c0000_*.anibnd*")):
            if not sibling.is_file():
                continue
            stem = sibling.name.split(".")[0]
            if stem not in stems:
                stems.append(stem)

    # Also probe known DLC stems via the full project/game search (they may live in a different root).
    for stem in _C0000_ATTACK_ANIBND_STEMS:
        if stem not in stems and _resolve_anibnd_path(settings, stem) is not None:
            stems.append(stem)

    return stems


def find_attack_animation_entry(
    settings,
    sub_anibnd_stem: str,
    anim_stem: str,
) -> tuple[DivBinder, BinderEntry] | None:
    """Find an HKX attack clip across c0000 ANIBNDs (selected stem first, then base + DLC)."""
    stems_to_try = [sub_anibnd_stem] if sub_anibnd_stem else []
    stems_to_try.extend(s for s in list_c0000_sub_anibnd_stems(settings) if s not in stems_to_try)

    anim_lower = anim_stem.lower()

    for stem in stems_to_try:
        sub_path = _resolve_anibnd_path(settings, stem)
        if sub_path is None:
            continue
        try:
            anibnd = DivBinder.from_path(sub_path)
        except Exception:
            continue
        for entry in anibnd.entries:
            if entry.stem.lower() == anim_lower and _HKX_ENTRY_RE.match(entry.name):
                return anibnd, entry
        try:
            entry_id = anim_id_to_binder_entry_id(int(anim_stem.split("_")[1]))
            entry = anibnd[entry_id]
            if _HKX_ENTRY_RE.match(entry.name):
                return anibnd, entry
        except (KeyError, TypeError, ValueError, IndexError):
            pass
    return None


def _attack_slot_enum_items(self, context):
    return StanLoadWeaponAttackAnimation._attack_slot_items


class StanLoadWeaponAttackAnimation(LoggingOperator):
    """Load a c0000 weapon attack clip onto the player c0000 armature."""

    bl_idname = "stan_tools.load_weapon_attack_animation"
    bl_label = "Load Weapon Attack"
    bl_description = (
        "Import a c0000 attack animation (by attack slot) onto the loaded player c0000 armature. "
        "Uses wepmotionCategory from EquipParamWeapon"
    )
    bl_options = {"REGISTER", "UNDO"}

    _attack_slot_items: list[tuple[str, str, str]] = [
        (slot.id, slot.label, f"{slot.label} ({slot.hand_offset}+{slot.action_offset})")
        for slot in ATTACK_SLOTS
    ]

    attack_slot: bpy.props.EnumProperty(
        name="Attack Slot",
        description="Weapon attack animation slot (DS1 hand/action offset schema)",
        items=_attack_slot_enum_items,
    )

    @classmethod
    def poll(cls, context) -> bool:
        if not context.scene.soulstruct_settings.game_config.supports_animation:
            return False
        stan = context.scene.stan_tools_settings
        return bool(stan.weapon_stem) and is_player_character_loaded(context)

    def invoke(self, context, event):
        stan = context.scene.stan_tools_settings
        if stan.weapon_attack_slot:
            self.attack_slot = stan.weapon_attack_slot
        return self.execute(context)

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        settings = self.settings(context)

        if not stan.weapon_stem:
            return self.error("Import a weapon first (Search Weapon by Name).")

        try:
            row_id = int(stan.weapon_row_id)
        except ValueError:
            return self.error("Active weapon row id is invalid. Re-import the weapon.")

        weapon = get_weapon_row(settings, stan, row_id)
        if weapon is None:
            return self.error(f"Could not resolve weapon row {row_id}.")
        if weapon.wepmotion_category <= 0:
            return self.error(
                f"No wepmotionCategory for row {row_id}. Point EquipParamWeapon XML in Setup or regenerate weapon_names."
            )

        stan_debug(
            self,
            f"Load weapon attack: stem={stan.weapon_stem!r}, row_id={row_id}, "
            f"wepmotionCategory={weapon.wepmotion_category}, slot={self.attack_slot!r}",
        )

        slot = get_attack_slot(self.attack_slot)
        if slot is None:
            return self.error("Invalid attack slot.")

        armature_obj = find_c0000_armature(context)
        if armature_obj is None:
            return self.error("Player c0000 armature not found. Load player character first.")
        stan_debug(self, f"Using player armature: {armature_obj.name!r}")

        er_family = settings.is_er_family()
        anim_stem = attack_hkx_stem(
            weapon.wepmotion_category,
            slot.hand_offset,
            slot.action_offset,
            er_family=er_family,
        )
        stan_debug(
            self,
            f"Resolved anim_stem={anim_stem!r} (er_family={er_family}, "
            f"wepmotion={weapon.wepmotion_category}, slot={slot.label})",
        )

        sub_stem = stan.c0000_sub_anibnd or ""
        searched_stems = list_c0000_sub_anibnd_stems(settings)
        stan_debug(
            self,
            f"Searching c0000 ANIBNDs {searched_stems!r} (selected sub={sub_stem!r}) for {anim_stem}.",
        )
        found = find_attack_animation_entry(settings, sub_stem, anim_stem)
        if found is None:
            searched = ", ".join(searched_stems) or "<none found>"
            hint = ""
            if anim_stem.startswith("a") and not anim_stem.startswith("a000"):
                # ER/NR moveset clip; high wepmotion categories are usually DLC movesets.
                hint = (
                    " This looks like a DLC moveset clip — its animations live in a DLC binder "
                    "(e.g. c0000_dlc02.anibnd), which must be present in your project or game chr/ folder."
                )
            return self.error(
                f"Attack clip {anim_stem} not found in c0000 ANIBNDs [{searched}] "
                f"(wepmotion {weapon.wepmotion_category}, slot {slot.label}).{hint}"
            )

        anim_anibnd, entry = found
        stan_debug(
            self,
            f"Found attack clip entry {entry.name!r} in sub-ANIBND {anim_anibnd.path.name!r}",
        )

        try:
            _skeleton_anibnd, skeleton_hkx, compendium = load_character_anibnd_bundle(settings, "c0000")
        except Exception as ex:
            return self.error(f"Cannot load c0000 skeleton: {ex}")

        ImportHKXAnimationWithBinderChoice.BINDER = anim_anibnd
        ImportHKXAnimationWithBinderChoice.ARMATURE_OBJ = armature_obj
        ImportHKXAnimationWithBinderChoice.PART_MESH_OBJ = None
        ImportHKXAnimationWithBinderChoice.MODEL_NAME = "c0000"
        ImportHKXAnimationWithBinderChoice.SKELETON_HKX = skeleton_hkx
        ImportHKXAnimationWithBinderChoice.HKX_COMPENDIUM = compendium

        stan_debug(self, f"Importing HKX animation entry {entry.name!r} onto {armature_obj.name!r}")
        result = import_character_hkx_animation_entry(
            self,
            context,
            entry=entry,
            binder=anim_anibnd,
            armature_obj=armature_obj,
            part_mesh_obj=None,
            model_name="c0000",
            skeleton_hkx=skeleton_hkx,
            compendium=compendium,
        )
        if result == {"FINISHED"}:
            stan_info(self, f"Loaded {anim_stem} ({slot.label}) on player c0000.")
        else:
            stan_warning(self, f"Attack animation import returned {result!r} for {anim_stem}")
        return result
