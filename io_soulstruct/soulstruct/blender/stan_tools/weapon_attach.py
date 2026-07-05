"""Attach imported weapon armatures to c0000 player hand (WepAbsorpPos)."""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix

from soulstruct.blender.flver.models.types.bl_flver_dummy import BlenderFLVERDummy

from .debug_log import stan_debug, stan_info, stan_warning
from .equip_weapon_param import WeaponRow, get_weapon_row
from .equipment_assembly import find_c0000_armature
from .wep_absorp_param import (
    get_wep_absorp_pos,
    hand_bone_from_disp_pos_type,
    route_global_dummy_id,
)
from .weapon_context import find_weapon_armature

__all__ = [
    "attach_weapon_to_player",
    "attach_weapon_to_c0000",
]

# Live-tunable orientation correction applied after parenting to the WepAbsorpPos dummy.
# Mirrors DSAS Matrix.CreateRotationX(Pi) on the weapon model (ER/NR family).
ER_WEAPON_CORRECTION = Matrix.Rotation(math.radians(180.0), 4, "X")


def find_c0000_dummy_by_reference_id(c0000_armature, reference_id: int):
    """Return the FLVER dummy Empty child of c0000 with the given reference id, or None."""
    for child in c0000_armature.children:
        if child.type != "EMPTY":
            continue
        match = BlenderFLVERDummy.DUMMY_NAME_RE.match(child.name)
        if match is None:
            continue
        try:
            ref_id = int(match.group("reference_id")[1:-1])
        except (TypeError, ValueError):
            continue
        if ref_id == reference_id:
            return child
    return None


def _attach_weapon_to_hand_bone(
    c0000: bpy.types.Object,
    weapon: bpy.types.Object,
    hand_bone: str,
    weapon_stem: str,
    operator=None,
) -> bool:
    """Parent weapon armature to c0000 hand bone (legacy / fallback path)."""
    if hand_bone not in c0000.data.bones:
        stan_warning(operator, f"Hand bone {hand_bone!r} not on c0000; falling back to R_Hand.")
        hand_bone = "R_Hand" if "R_Hand" in c0000.data.bones else next(iter(c0000.data.bones), "")

    if not hand_bone:
        stan_warning(operator, "c0000 has no bones; cannot attach weapon.")
        return False

    weapon.parent = c0000
    weapon.parent_type = "BONE"
    weapon.parent_bone = hand_bone
    weapon.location = (0.0, 0.0, 0.0)
    weapon.rotation_mode = "QUATERNION"
    weapon.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    weapon.scale = (1.0, 1.0, 1.0)

    stan_info(operator, f"Attached {weapon_stem} to c0000.{hand_bone}.")
    return True


def attach_weapon_to_player(
    context: bpy.types.Context,
    weapon_row: WeaponRow,
    weapon_stem: str,
    settings,
    stan,
    operator=None,
) -> bool:
    """Parent weapon armature to c0000 hand bone using WepAbsorpPosParam."""
    c0000 = find_c0000_armature(context)
    if c0000 is None:
        stan_warning(operator, f"Cannot attach {weapon_stem}: c0000 armature not in scene.")
        return False

    weapon = find_weapon_armature(context, weapon_stem, operator=operator)
    if weapon is None:
        stan_warning(operator, f"Cannot attach weapon: armature for {weapon_stem!r} not found.")
        return False

    hand_bone = "R_Hand"
    absorp = get_wep_absorp_pos(settings, stan, weapon_row.absorp_param_id)
    if absorp is not None:
        hand_bone = hand_bone_from_disp_pos_type(absorp.disp_pos_type_right_0)
        stan_debug(
            operator,
            f"WepAbsorpPos row {absorp.row_id}: right_0={absorp.right_0}, "
            f"dispPosType={absorp.disp_pos_type_right_0} → bone {hand_bone!r}, "
            f"isSkeletonBind={absorp.is_skeleton_bind}",
        )
        if absorp.is_skeleton_bind:
            stan_debug(
                operator,
                "isSkeletonBind=1 — using bone parent (full skeleton bind not implemented).",
            )
        elif absorp.right_0 >= 0:
            manager, local_ref_id = route_global_dummy_id(absorp.right_0)
            if manager == 0 and local_ref_id >= 0:
                dummy_empty = find_c0000_dummy_by_reference_id(c0000, local_ref_id)
                if dummy_empty is not None:
                    er_family = settings.is_er_family()
                    correction = ER_WEAPON_CORRECTION if er_family else Matrix.Identity(4)

                    weapon.parent = dummy_empty
                    weapon.parent_type = "OBJECT"
                    weapon.matrix_parent_inverse = dummy_empty.matrix_world.inverted()
                    weapon.matrix_world = dummy_empty.matrix_world @ correction

                    stan_info(
                        operator,
                        f"Attached {weapon_stem} to c0000 dummy {dummy_empty.name!r} "
                        f"(reference id {local_ref_id}).",
                    )
                    return True
                stan_debug(
                    operator,
                    f"No c0000 dummy with reference id {local_ref_id}; falling back to hand bone.",
                )
            elif manager != 0:
                stan_debug(
                    operator,
                    f"WepAbsorpPos right_0 manager={manager} (weapon-mounted dummy not supported); "
                    f"falling back to hand bone.",
                )
    else:
        stan_debug(operator, f"No WepAbsorpPos for absorpParamId={weapon_row.absorp_param_id}; using R_Hand.")

    return _attach_weapon_to_hand_bone(c0000, weapon, hand_bone, weapon_stem, operator=operator)


def attach_weapon_to_c0000(
    context: bpy.types.Context,
    weapon_stem: str,
    operator=None,
) -> bool:
    """Legacy wrapper — attaches with default R_Hand when no WeaponRow available."""
    from .equip_weapon_param import WeaponRow

    stan = context.scene.stan_tools_settings
    settings = context.scene.soulstruct_settings
    try:
        row_id = int(stan.weapon_row_id)
    except ValueError:
        row_id = 0
    weapon_row = get_weapon_row(settings, stan, row_id) if row_id else None
    if weapon_row is None:
        weapon_row = WeaponRow(
            row_id=row_id,
            name=weapon_stem,
            equip_model_id=0,
            stem=weapon_stem,
            wepmotion_category=0,
            absorp_param_id=-1,
        )
    return attach_weapon_to_player(
        context,
        weapon_row,
        weapon_stem,
        settings,
        stan,
        operator=operator,
    )
