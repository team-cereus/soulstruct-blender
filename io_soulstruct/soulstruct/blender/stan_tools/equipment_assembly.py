"""Assemble ER preview body parts onto c0000 (DSAS NewChrAsm DirectBoneMap).

DSAS parity (ER player character):

- ``c0000.chrbnd`` is skeleton-only (488 bones, no meshes).
- Armor arrives as separate PARTSBND armatures (BD/AM/LG/HD), each with its own
  bind pose. Shared bone names exist but rest transforms differ — do **not** merge
  armatures or parent equip objects to c0000 (that double-transforms and deforms).
- ``DirectBoneMap``: follower armatures keep their bind pose; matching bones get
  COPY_TRANSFORMS constraints from the c0000 leader (FK copy only).
- Assembly update order: legs → body → arms → head.
"""

from __future__ import annotations

import bpy

from soulstruct.blender.general.properties import SoulstructSettings
from soulstruct.games import NIGHTREIGN

from .debug_log import stan_debug, stan_info, stan_warning

__all__ = [
    "find_c0000_armature",
    "find_equip_armature_by_prefix",
    "find_equip_armature_by_stem",
    "glue_equipment_part_to_c0000",
    "apply_direct_bone_map_to_c0000",
    "hide_player_skeleton_display",
    "hide_c0000_dummies",
    "resolve_assembly_mode",
    "assemble_er_preview_after_import",
]

# DSAS update order: legs → body → arms → head (see NewChrAsm boneMappersAndGluersUpdateOrder).
_ER_LEGS_PREFIXES = ("lg_m_", "lg_f_")
_ER_BODY_PREFIXES = ("bd_m_", "bd_f_")
_ER_ARMS_PREFIXES = ("am_m_", "am_f_")
_ER_HEAD_PREFIXES = ("hd_m_", "hd_f_")

_DSAS_SLOT_ORDER = (
    _ER_LEGS_PREFIXES,
    _ER_BODY_PREFIXES,
    _ER_ARMS_PREFIXES,
    _ER_HEAD_PREFIXES,
)


def find_c0000_armature(context: bpy.types.Context) -> bpy.types.Object | None:
    """Return the imported c0000 player armature, if any."""
    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and obj.name.lower().startswith("c0000"):
            return obj
    return None


def _armature_name_matches_stem(armature_name: str, stem: str) -> bool:
    """True when armature object name starts with ``stem`` (case-insensitive)."""
    return armature_name.lower().startswith(stem.lower())


def find_equip_armature_by_stem(
    context: bpy.types.Context,
    stem: str,
) -> bpy.types.Object | None:
    """Find armature whose name starts with ``stem`` (e.g. ``lg_m_1500`` → ``LG_M_1500 Armature``)."""
    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and _armature_name_matches_stem(obj.name, stem):
            return obj
    return None


def find_equip_armature_by_prefix(
    context: bpy.types.Context,
    prefixes: tuple[str, ...],
) -> bpy.types.Object | None:
    """Find first armature whose name starts with one of ``prefixes`` (case-insensitive)."""
    for obj in context.scene.objects:
        if obj.type != "ARMATURE":
            continue
        name_lower = obj.name.lower()
        if any(name_lower.startswith(p) for p in prefixes):
            return obj
    return None


def _dsas_slot_index(stem: str) -> int:
    """Sort key for DSAS assembly order: legs, body, arms, head."""
    lower = stem.lower()
    for index, prefixes in enumerate(_DSAS_SLOT_ORDER):
        if lower.startswith(prefixes):
            return index
    return len(_DSAS_SLOT_ORDER)


def _shared_bone_names(
    leader_armature: bpy.types.Object,
    equip_armature: bpy.types.Object,
) -> list[str]:
    """Return bone names present on both armatures (DSAS DirectBoneMap name match)."""
    leader_names = {bone.name for bone in leader_armature.data.bones}
    return sorted(
        bone.name for bone in equip_armature.data.bones if bone.name in leader_names
    )


def _resolve_glue_pairs(
    leader_armature: bpy.types.Object,
    equip_armature: bpy.types.Object,
    candidates: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Pick glue pairs that exist on both armatures."""
    leader_bones = leader_armature.data.bones
    follower_bones = equip_armature.data.bones
    resolved: list[tuple[str, str]] = []
    for leader_bone, follower_bone in candidates:
        if leader_bone in leader_bones and follower_bone in follower_bones:
            resolved.append((leader_bone, follower_bone))
    return resolved


def resolve_assembly_mode(settings: SoulstructSettings) -> str:
    """Return DSAS skeleton-remap mode for armor assembly (ER vs Nightreign).

    ER uses DirectBoneMap (COPY_TRANSFORMS on shared bone names).
    Nightreign uses RetargetRelativeAndDirectFKOrientation in DSAS; we expose
    ``NR_RETARGET`` as a seam for future relative-retarget work.
    """
    if settings.is_game(NIGHTREIGN):
        return "NR_RETARGET"
    return "DIRECT_BONE_MAP"


def _is_flver_dummy_empty_name(name: str) -> bool:
    """True for FLVER dummy empties like ``c0000 Dummy<279> [15]``."""
    if "Dummy<" not in name and "Dummy " not in name:
        return False
    return "[" in name and "]" in name


def hide_c0000_dummies(
    c0000_armature: bpy.types.Object,
    hide: bool = True,
    operator=None,
) -> int:
    """Hide/show FLVER dummy empties parented to c0000 (viewport declutter for weapon testing)."""
    if c0000_armature is None:
        return 0

    count = 0
    for child in c0000_armature.children:
        if child.type != "EMPTY":
            continue
        if not _is_flver_dummy_empty_name(child.name):
            continue
        child.hide_set(hide)
        child.hide_viewport = hide
        count += 1

    stan_debug(
        operator,
        f"{'Hidden' if hide else 'Shown'} {count} c0000 FLVER dummy empties "
        f"under {c0000_armature.name!r}.",
    )
    return count


# Name prefixes for non-deform control/helper bones (Havok IK / look-at / twist control rig).
# These carry no mesh weights, so hiding them only removes viewport clutter.
_NON_DEFORM_BONE_PREFIXES = ("ctrl_",)


def _is_non_deform_bone(bone_name: str) -> bool:
    """True for control/helper bones (e.g. ``ctrl_*``) that do not skin the mesh."""
    lowered = bone_name.lower()
    return any(lowered.startswith(prefix) for prefix in _NON_DEFORM_BONE_PREFIXES)


def hide_player_skeleton_display(c0000_armature: bpy.types.Object) -> None:
    """Hide c0000 control-rig clutter (ctrl_* bones); keep deform bones visible.

    `bpy.types.Armature` has no `show_bones`; we toggle each bone's `hide` flag instead.
    `Bone.hide` is display-only: hidden bones still animate and still drive child/deform
    bones, so this never changes how the character looks or moves. Idempotent — deform
    bones are explicitly un-hidden so re-running normalizes either prior state.
    """
    if c0000_armature is None:
        return

    for bone in c0000_armature.data.bones:
        bone.hide = _is_non_deform_bone(bone.name)
    for child in c0000_armature.children:
        if child.type == "MESH" and "<EMPTY>" in child.name:
            child.hide_set(True)
            child.hide_viewport = True


def apply_direct_bone_map_to_c0000(
    context: bpy.types.Context,
    equip_armature: bpy.types.Object,
    c0000_armature: bpy.types.Object,
    operator=None,
) -> int:
    """Map shared bones from equip armature to c0000 via COPY_TRANSFORMS (DirectBoneMap).

    Follower armatures keep their own bind pose and world transform. Object parenting
    to c0000 is never applied — that would double-transform and cause deformation.
    """
    if equip_armature is None or c0000_armature is None:
        return 0

    if equip_armature.parent is not None:
        world_matrix = equip_armature.matrix_world.copy()
        equip_armature.parent = None
        equip_armature.matrix_world = world_matrix
        stan_debug(
            operator,
            f"Cleared parent on equip armature {equip_armature.name!r} "
            "(DirectBoneMap: no object parenting).",
        )

    shared = _shared_bone_names(c0000_armature, equip_armature)
    if not shared:
        stan_warning(
            operator,
            f"No shared bones for {equip_armature.name!r} → {c0000_armature.name!r}; "
            "skipping DirectBoneMap constraints.",
        )
        return 0

    mapped = 0
    for bone_name in shared:
        pose_bone = equip_armature.pose.bones.get(bone_name)
        if pose_bone is None:
            continue
        con_name = f"StanMap_{bone_name}"
        con = pose_bone.constraints.get(con_name)
        if con is None:
            con = pose_bone.constraints.new("COPY_TRANSFORMS")
            con.name = con_name
        con.target = c0000_armature
        con.subtarget = bone_name
        con.target_space = "POSE"
        con.owner_space = "POSE"
        mapped += 1
        stan_debug(
            operator,
            f"DirectBoneMap {equip_armature.name!r}.{bone_name} ← "
            f"{c0000_armature.name!r}.{bone_name}",
        )

    return mapped


def glue_equipment_part_to_c0000(
    context: bpy.types.Context,
    equip_armature: bpy.types.Object,
    glue_pairs: list[tuple[str, str]],
    leader_armature: bpy.types.Object,
    operator=None,
) -> bool:
    """Parent equip armature to leader and glue bones via COPY_TRANSFORMS constraints."""
    if equip_armature is None or leader_armature is None:
        return False

    resolved = _resolve_glue_pairs(leader_armature, equip_armature, glue_pairs)
    if not resolved:
        stan_warning(
            operator,
            f"No matching glue bones for {equip_armature.name!r} → {leader_armature.name!r}; "
            "parenting armature object only.",
        )

    if equip_armature.parent != leader_armature:
        equip_armature.parent = leader_armature
        equip_armature.parent_type = "OBJECT"
        equip_armature.matrix_parent_inverse = leader_armature.matrix_world.inverted()
        stan_debug(
            operator,
            f"Parented equip armature {equip_armature.name!r} to {leader_armature.name!r}",
        )

    for leader_bone, follower_bone in resolved:
        pose_bone = equip_armature.pose.bones.get(follower_bone)
        if pose_bone is None:
            continue
        con_name = f"StanGlue_{leader_bone}"
        con = pose_bone.constraints.get(con_name)
        if con is None:
            con = pose_bone.constraints.new("COPY_TRANSFORMS")
            con.name = con_name
        con.target = leader_armature
        con.subtarget = leader_bone
        con.target_space = "POSE"
        con.owner_space = "POSE"
        stan_debug(
            operator,
            f"Glue {equip_armature.name!r}.{follower_bone} ← {leader_armature.name!r}.{leader_bone}",
        )

    return bool(resolved)


def assemble_er_preview_after_import(
    context: bpy.types.Context,
    operator=None,
    part_stems: list[str] | None = None,
) -> None:
    """Map imported BD/AM/LG/HD preview parts onto c0000 (DSAS DirectBoneMap per part).

    When ``part_stems`` is given, each stem is resolved to an armature by exact name
    prefix (e.g. ``lg_m_1500``). Parts are assembled in DSAS order: legs, body,
    arms, head — regardless of list order.
    """
    c0000 = find_c0000_armature(context)
    if c0000 is None:
        stan_warning(operator, "ER preview assembly skipped: no c0000 armature in scene.")
        return

    settings = SoulstructSettings.from_context(context)
    assembly_mode = resolve_assembly_mode(settings)
    stan_debug(
        operator,
        f"Armor assembly mode: {assembly_mode!r} "
        f"(game={settings.game_variable_name!r}).",
    )
    if assembly_mode == "NR_RETARGET":
        # Known approximation: COPY_TRANSFORMS (DirectBoneMap) is correct when NR
        # follower bind poses match c0000. True relative retarget (DSAS
        # RetargetRelativeAndDirectFKOrientation) is a future refinement.
        stan_debug(
            operator,
            "NR_RETARGET: using COPY_TRANSFORMS approximation until relative retarget is implemented.",
        )

    hide_player_skeleton_display(c0000)
    stan_debug(operator, f"Assembling ER preview body around {c0000.name!r}")

    if part_stems:
        ordered_stems = sorted(part_stems, key=_dsas_slot_index)
        parts: list[bpy.types.Object] = []
        for stem in ordered_stems:
            part = find_equip_armature_by_stem(context, stem)
            if part is not None:
                apply_direct_bone_map_to_c0000(context, part, c0000, operator)
                parts.append(part)
            else:
                stan_warning(operator, f"ER preview assembly: no armature for stem {stem!r}.")
    else:
        legs = find_equip_armature_by_prefix(context, _ER_LEGS_PREFIXES)
        body = find_equip_armature_by_prefix(context, _ER_BODY_PREFIXES)
        arms = find_equip_armature_by_prefix(context, _ER_ARMS_PREFIXES)
        head = find_equip_armature_by_prefix(context, _ER_HEAD_PREFIXES)
        parts = []
        for part in (legs, body, arms, head):
            if part is not None:
                apply_direct_bone_map_to_c0000(context, part, c0000, operator)
                parts.append(part)

    if parts:
        stan_info(operator, f"Assembled ER preview parts onto c0000: {', '.join(p.name for p in parts)}.")
    else:
        stan_warning(operator, "ER preview assembly: no BD/AM/LG/HD armatures found.")

    hide_c0000_dummies(c0000, hide=True, operator=operator)
