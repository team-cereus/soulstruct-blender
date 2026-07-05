"""Weapon attack animation slot definitions (wepmotionCategory schema).

DS1 attack clip ids: ``wepmotionCategory * 10000 + hand_offset + action_offset``
with HKX stems ``a000_{suffix:06d}``.

ER/NR use ``wepmotionCategory`` in EquipParamWeapon but HKX stems are
``a{wepmotion:03d}_{sub:06d}`` where ``sub = (hand_offset // 1000) * 10000 + action_part``
and combo 2nd-hit ``action_offset`` 1 maps to ``action_part`` 10.
"""

from __future__ import annotations

from dataclasses import dataclass

# Hand offsets in the DS1 attack animation id scheme.
HAND_OFFSET_RH = 3000
HAND_OFFSET_2H = 4000
HAND_OFFSET_LH = 5000


@dataclass(frozen=True, slots=True)
class AttackSlot:
    id: str
    label: str
    hand_offset: int
    action_offset: int


ATTACK_SLOTS: list[AttackSlot] = [
    AttackSlot("light_rh_a", "Light RH (1st)", HAND_OFFSET_RH, 0),
    AttackSlot("light_rh_b", "Light RH (2nd)", HAND_OFFSET_RH, 1),
    AttackSlot("heavy_rh", "Heavy RH", HAND_OFFSET_RH, 300),
    AttackSlot("heavy_rh_chain", "Heavy RH (chain)", HAND_OFFSET_RH, 301),
    AttackSlot("kick", "Kick", HAND_OFFSET_RH, 100),
    AttackSlot("running_rh", "Running RH", HAND_OFFSET_RH, 500),
    AttackSlot("jump_rh", "Jump RH", HAND_OFFSET_RH, 600),
    AttackSlot("fall_rh", "Fall RH", HAND_OFFSET_RH, 640),
    AttackSlot("light_2h_a", "Light 2H (1st)", HAND_OFFSET_2H, 0),
    AttackSlot("light_2h_b", "Light 2H (2nd)", HAND_OFFSET_2H, 1),
    AttackSlot("heavy_2h", "Heavy 2H", HAND_OFFSET_2H, 300),
    AttackSlot("heavy_2h_chain", "Heavy 2H (chain)", HAND_OFFSET_2H, 301),
    AttackSlot("running_2h", "Running 2H", HAND_OFFSET_2H, 500),
    AttackSlot("jump_2h", "Jump 2H", HAND_OFFSET_2H, 600),
    AttackSlot("fall_2h", "Fall 2H", HAND_OFFSET_2H, 640),
    AttackSlot("light_lh", "Light LH", HAND_OFFSET_LH, 0),
    AttackSlot("heavy_lh", "Heavy LH", HAND_OFFSET_LH, 300),
    AttackSlot("running_lh", "Running LH", HAND_OFFSET_LH, 500),
    AttackSlot("jump_lh", "Jump LH", HAND_OFFSET_LH, 600),
    AttackSlot("fall_lh", "Fall LH", HAND_OFFSET_LH, 640),
    AttackSlot("dual_light", "Dual-wield light", HAND_OFFSET_RH, 310),
    AttackSlot("dual_heavy", "Dual-wield heavy", HAND_OFFSET_RH, 320),
]

_ATTACK_SLOT_BY_ID = {slot.id: slot for slot in ATTACK_SLOTS}


def get_attack_slot(slot_id: str) -> AttackSlot | None:
    return _ATTACK_SLOT_BY_ID.get(slot_id)


def compute_attack_anim_id(wepmotion_category: int, hand_offset: int, action_offset: int) -> int:
    """Full DS1-style c0000 attack animation id (e.g. 25 * 10000 + 3000 + 0 = 253000)."""
    return wepmotion_category * 10_000 + hand_offset + action_offset


def er_attack_action_part(action_offset: int) -> int:
    """ER/NR action part within a hand group (combo 2nd hit uses 10, not 1)."""
    if action_offset == 1:
        return 10
    return action_offset


def er_attack_sub_id(hand_offset: int, action_offset: int) -> int:
    """ER/NR six-digit sub-id inside ``a{wepmotion:03d}_{sub:06d}`` stems."""
    return (hand_offset // 1000) * 10_000 + er_attack_action_part(action_offset)


def anim_id_to_hkx_stem(anim_id: int) -> str:
    """DS1 HKX filename stem inside c0000 ANIBND (e.g. a000_253000)."""
    suffix = anim_id % 1_000_000
    return f"a000_{suffix:06d}"


def attack_hkx_stem(
    wepmotion_category: int,
    hand_offset: int,
    action_offset: int,
    *,
    er_family: bool,
) -> str:
    """Resolve attack HKX stem for DS1 or ER/NR family games."""
    if er_family:
        sub_id = er_attack_sub_id(hand_offset, action_offset)
        return f"a{wepmotion_category:03d}_{sub_id:06d}"
    anim_id = compute_attack_anim_id(wepmotion_category, hand_offset, action_offset)
    return anim_id_to_hkx_stem(anim_id)


def anim_id_to_binder_entry_id(anim_id: int) -> int:
    """Binder entry id for the attack clip (e.g. 1000253000)."""
    return 1_000_000_000 + (anim_id % 1_000_000)
