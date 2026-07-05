"""EquipParamWeapon XML loading for Stan's Tools weapon preview."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from soulstruct.blender.general.properties import SoulstructSettings

from soulstruct.blender.general.weapon_names import WeaponIndexEntry, get_weapon_index


@dataclass(frozen=True, slots=True)
class WeaponRow:
    row_id: int
    name: str
    equip_model_id: int
    stem: str
    wepmotion_category: int
    absorp_param_id: int = -1


def resolve_equip_weapon_xml_path(
    settings: SoulstructSettings,
    stan_settings,
) -> Path | None:
    stan = stan_settings
    if stan.equip_weapon_param_xml_path:
        path = Path(bpy.path.abspath(stan.equip_weapon_param_xml_path))
        if path.is_file():
            return path

    for root in (settings.project_root_path, settings.game_root_path):
        if root is None:
            continue
        for sub in ("regulation-bin", "param", "param/param"):
            candidate = root / sub / "EquipParamWeapon.param.xml"
            if candidate.is_file():
                return candidate
    return None


@lru_cache(maxsize=4)
def _load_xml_rows(xml_path: str, mtime_ns: int) -> dict[int, dict[str, int]]:
    del mtime_ns
    rows: dict[int, dict[str, int]] = {}
    path = Path(xml_path)
    for _event, row in ET.iterparse(path, events=("end",)):
        if row.tag != "row" or "id" not in row.attrib:
            continue
        try:
            row_id = int(row.attrib["id"])
        except ValueError:
            row.clear()
            continue
        parsed: dict[str, int] = {}
        for key in ("equipModelId", "wepmotionCategory", "weaponCategory", "absorpParamId"):
            if key in row.attrib:
                try:
                    parsed[key] = int(row.attrib[key])
                except ValueError:
                    pass
        if parsed:
            rows[row_id] = parsed
        row.clear()
    return rows


def get_weapon_row(
    settings: SoulstructSettings,
    stan_settings,
    row_id: int,
) -> WeaponRow | None:
    """Resolve weapon metadata from XML (preferred) or bundled index."""
    index = get_weapon_index(settings)
    index_entry: WeaponIndexEntry | None = index.get(row_id)

    xml_path = resolve_equip_weapon_xml_path(settings, stan_settings)
    xml_row: dict[str, int] = {}
    if xml_path is not None:
        xml_row = _load_xml_rows(str(xml_path), xml_path.stat().st_mtime_ns).get(row_id, {})

    if not index_entry and not xml_row:
        return None

    name = (index_entry or {}).get("name", f"Weapon {row_id}")
    equip_model_id = xml_row.get("equipModelId") or (index_entry or {}).get("equipModelId", 0)
    wepmotion = xml_row.get("wepmotionCategory") or (index_entry or {}).get("wepmotionCategory", 0)
    absorp_param_id = xml_row.get("absorpParamId", -1)
    stem = (index_entry or {}).get("stem", "")
    if not stem and equip_model_id > 0:
        stem = f"WP_A_{equip_model_id:04d}"

    return WeaponRow(
        row_id=row_id,
        name=name,
        equip_model_id=equip_model_id,
        stem=stem,
        wepmotion_category=wepmotion,
        absorp_param_id=absorp_param_id,
    )
