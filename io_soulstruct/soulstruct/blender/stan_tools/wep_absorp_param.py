"""WepAbsorpPosParam XML loading for weapon hand attachment."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from soulstruct.blender.general.properties import SoulstructSettings

__all__ = [
    "WepAbsorpRow",
    "resolve_wep_absorp_xml_path",
    "get_wep_absorp_pos",
    "hand_bone_from_disp_pos_type",
    "route_global_dummy_id",
]

# DSAS DispPosTypes: RightHand=0, LeftHand=1, Other=3
_DISP_POS_TO_BONE = {
    0: "R_Hand",
    1: "L_Hand",
}


@dataclass(frozen=True, slots=True)
class WepAbsorpRow:
    row_id: int
    right_0: int
    disp_pos_type_right_0: int
    is_skeleton_bind: bool


def hand_bone_from_disp_pos_type(disp_pos_type: int) -> str:
    """Map WepAbsorpPos dispPosType (0=R_Hand, 1=L_Hand) to c0000 bone name."""
    return _DISP_POS_TO_BONE.get(disp_pos_type, "R_Hand")


def route_global_dummy_id(dummy_id: int) -> tuple[int, int]:
    """Split a WepAbsorpPos dummy id into (manager, local_ref_id). manager 0 = body c0000."""
    if dummy_id is None or dummy_id < 0:
        return (-1, -1)
    if dummy_id >= 1000:
        return (dummy_id // 1000, dummy_id % 1000)
    return (0, dummy_id)


def resolve_wep_absorp_xml_path(
    settings: SoulstructSettings,
    stan_settings,
) -> Path | None:
    """Resolve WepAbsorpPosParam.param.xml (same search roots as EquipParamWeapon)."""
    if stan_settings.equip_weapon_param_xml_path:
        equip_path = Path(bpy.path.abspath(stan_settings.equip_weapon_param_xml_path))
        if equip_path.is_file():
            sibling = equip_path.parent / "WepAbsorpPosParam.param.xml"
            if sibling.is_file():
                return sibling

    for root in (settings.project_root_path, settings.game_root_path):
        if root is None:
            continue
        for sub in ("regulation-bin", "param", "param/param"):
            candidate = root / sub / "WepAbsorpPosParam.param.xml"
            if candidate.is_file():
                return candidate
    return None


@lru_cache(maxsize=4)
def _load_xml_rows(xml_path: str, mtime_ns: int) -> dict[int, WepAbsorpRow]:
    del mtime_ns
    rows: dict[int, WepAbsorpRow] = {}
    path = Path(xml_path)
    for _event, row in ET.iterparse(path, events=("end",)):
        if row.tag != "row" or "id" not in row.attrib:
            continue
        try:
            row_id = int(row.attrib["id"])
        except ValueError:
            row.clear()
            continue

        def _int_attr(key: str, default: int = 0) -> int:
            raw = row.attrib.get(key)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        right_0 = _int_attr("right_0", -1)
        disp_pos_type = _int_attr("dispPosType_right_0", 0)
        is_skeleton_bind = _int_attr("isSkeletonBind", 0) == 1

        rows[row_id] = WepAbsorpRow(
            row_id=row_id,
            right_0=right_0,
            disp_pos_type_right_0=disp_pos_type,
            is_skeleton_bind=is_skeleton_bind,
        )
        row.clear()
    return rows


def get_wep_absorp_pos(
    settings: SoulstructSettings,
    stan_settings,
    absorp_param_id: int,
) -> WepAbsorpRow | None:
    """Return WepAbsorpPos row for ``absorpParamId`` from EquipParamWeapon."""
    if absorp_param_id < 0:
        return None
    xml_path = resolve_wep_absorp_xml_path(settings, stan_settings)
    if xml_path is None:
        return None
    return _load_xml_rows(str(xml_path), xml_path.stat().st_mtime_ns).get(absorp_param_id)
