from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_equipment_assembly():
    stan_tools_dir = Path(__file__).resolve().parents[1] / "stan_tools"
    pkg_name = "stan_tools_equipment_assembly_test_pkg"

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(stan_tools_dir)]
    sys.modules[pkg_name] = pkg

    debug_path = stan_tools_dir / "debug_log.py"
    debug_qual = f"{pkg_name}.debug_log"
    debug_spec = importlib.util.spec_from_file_location(debug_qual, debug_path)
    debug_mod = importlib.util.module_from_spec(debug_spec)
    assert debug_spec.loader is not None
    sys.modules[debug_qual] = debug_mod
    debug_spec.loader.exec_module(debug_mod)

    ea_path = stan_tools_dir / "equipment_assembly.py"
    ea_qual = f"{pkg_name}.equipment_assembly"
    ea_spec = importlib.util.spec_from_file_location(ea_qual, ea_path)
    ea_mod = importlib.util.module_from_spec(ea_spec)
    assert ea_spec.loader is not None
    sys.modules[ea_qual] = ea_mod
    ea_spec.loader.exec_module(ea_mod)
    return ea_mod


_ea = _load_equipment_assembly()
_shared_bone_names = _ea._shared_bone_names
_armature_name_matches_stem = _ea._armature_name_matches_stem
_apply_direct_bone_map_to_c0000 = _ea.apply_direct_bone_map_to_c0000


def _mock_armature(bone_names: list[str]):
    """Armature mock with Blender-like ``data.bones`` (iterates Bone objects with .name)."""
    arm = MagicMock()
    bones = [MagicMock(name=name) for name in bone_names]
    for bone, name in zip(bones, bone_names, strict=True):
        bone.name = name
    arm.data.bones = bones
    return arm


def test_shared_bone_names_returns_intersection_sorted():
    leader = _mock_armature(["Pelvis", "L_Thigh", "R_Thigh", "Spine"])
    equip = _mock_armature(["Pelvis", "R_Thigh", "L_Thigh", "L_Calf", "R_Calf"])
    assert _shared_bone_names(leader, equip) == ["L_Thigh", "Pelvis", "R_Thigh"]


def test_shared_bone_names_empty_when_no_overlap():
    leader = _mock_armature(["Pelvis", "Spine"])
    equip = _mock_armature(["BD_Root", "Offset_L_Clavicle"])
    assert _shared_bone_names(leader, equip) == []


def test_shared_bone_names_all_shared():
    bones = ["Pelvis", "L_Thigh", "R_Thigh", "L_Calf", "R_Calf"]
    leader = _mock_armature(bones)
    equip = _mock_armature(bones)
    assert _shared_bone_names(leader, equip) == sorted(bones)


def test_shared_bone_names_uses_equip_bone_order_via_sort():
    leader = _mock_armature(["Z_Bone", "A_Bone", "M_Bone"])
    equip = _mock_armature(["M_Bone", "A_Bone", "Z_Bone", "Extra"])
    assert _shared_bone_names(leader, equip) == ["A_Bone", "M_Bone", "Z_Bone"]


def test_armature_name_matches_stem_case_insensitive():
    assert _armature_name_matches_stem("LG_M_1500 Armature", "lg_m_1500")
    assert _armature_name_matches_stem("hd_f_0000", "HD_F_0000")
    assert not _armature_name_matches_stem("BD_M_1501 Armature", "lg_m_1500")


def test_apply_direct_bone_map_clears_parent_and_does_not_reparent():
    """DirectBoneMap must not parent equip armature to c0000 (DSAS parity)."""
    pose_bone = MagicMock()
    pose_bone.constraints = MagicMock()
    pose_bone.constraints.get.return_value = None
    new_con = MagicMock()
    pose_bone.constraints.new.return_value = new_con

    equip = MagicMock()
    equip.name = "LG_M_1500 Armature"
    equip.parent = MagicMock(name="old_parent")
    world_copy = MagicMock()
    equip.matrix_world.copy.return_value = world_copy
    equip.data.bones = [MagicMock(name="Pelvis")]
    equip.data.bones[0].name = "Pelvis"
    equip.pose.bones.get.return_value = pose_bone

    c0000 = MagicMock()
    c0000.name = "c0000 Armature"
    c0000.data.bones = [MagicMock(name="Pelvis")]
    c0000.data.bones[0].name = "Pelvis"

    context = MagicMock()
    mapped = _apply_direct_bone_map_to_c0000(context, equip, c0000)

    assert equip.parent is None
    assert equip.matrix_world is world_copy
    assert mapped == 1
    new_con.target = c0000
    new_con.subtarget = "Pelvis"
