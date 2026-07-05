from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_weapon_attack_slots():
    path = Path(__file__).resolve().parents[1] / "stan_tools" / "weapon_attack_slots.py"
    qual = "stan_tools_weapon_attack_slots_test"
    spec = importlib.util.spec_from_file_location(qual, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)
    return mod


_was = _load_weapon_attack_slots()
HAND_OFFSET_RH = _was.HAND_OFFSET_RH
attack_hkx_stem = _was.attack_hkx_stem
compute_attack_anim_id = _was.compute_attack_anim_id
er_attack_sub_id = _was.er_attack_sub_id


def test_er_backhand_light_rh():
    assert er_attack_sub_id(HAND_OFFSET_RH, 0) == 30_000
    assert attack_hkx_stem(58, HAND_OFFSET_RH, 0, er_family=True) == "a058_030000"


def test_er_backhand_light_rh_b():
    assert er_attack_sub_id(HAND_OFFSET_RH, 1) == 30_010
    assert attack_hkx_stem(58, HAND_OFFSET_RH, 1, er_family=True) == "a058_030010"


def test_er_backhand_heavy():
    assert attack_hkx_stem(58, HAND_OFFSET_RH, 300, er_family=True) == "a058_030300"


def test_ds1_dagger_light():
    anim_id = compute_attack_anim_id(25, HAND_OFFSET_RH, 0)
    assert anim_id == 253_000
    assert attack_hkx_stem(25, HAND_OFFSET_RH, 0, er_family=False) == "a000_253000"
