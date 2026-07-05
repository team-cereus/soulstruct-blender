"""EquipParamProtector XML loading for Stan's Tools player preview armor stems."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from soulstruct.blender.general.properties import SoulstructSettings

_SLOT_PREFIXES = (
    ("headEquip", "HD"),
    ("bodyEquip", "BD"),
    ("armEquip", "AM"),
    ("legEquip", "LG"),
)

_ER_DEFAULT_PROTECTORS = {
    "head": 980_000,
    "body": 981_100,
    "arms": 980_200,
    "legs": 980_300,
}

_NR_DEFAULT_PROTECTORS = {
    "head": 5_000_000,
    "body": 5_000_100,
    "arms": 5_000_200,
    "legs": 5_000_300,
}

# DSAS assembly order: legs → body → arms → head.
_DSAS_SLOT_ORDER = ("legs", "body", "arms", "head")


def resolve_equip_protector_xml_path(
    settings: SoulstructSettings,
    stan_settings,
) -> Path | None:
    stan = stan_settings
    override_path = getattr(stan, "equip_protector_param_xml_path", "")
    if override_path:
        path = Path(bpy.path.abspath(override_path))
        if path.is_file():
            return path

    for root in (settings.project_root_path, settings.game_root_path):
        if root is None:
            continue
        for sub in ("regulation-bin", "param", "param/param"):
            candidate = root / sub / "EquipParamProtector.param.xml"
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
        for key in (
            "equipModelId",
            "headEquip",
            "bodyEquip",
            "armEquip",
            "legEquip",
            "equipModelGender",
        ):
            if key in row.attrib:
                try:
                    parsed[key] = int(row.attrib[key])
                except ValueError:
                    pass
        if parsed:
            rows[row_id] = parsed
        row.clear()
    return rows


def protector_stem_for_row(row: dict, female: bool) -> str | None:
    """Return PARTSBND stem (e.g. ``bd_m_1501``) from a protector row, or None."""
    equip_model_id = row.get("equipModelId")
    if equip_model_id is None:
        return None

    prefix: str | None = None
    for flag_key, slot_prefix in _SLOT_PREFIXES:
        if row.get(flag_key) == 1:
            prefix = slot_prefix
            break
    if prefix is None:
        return None

    gender = "f" if female else "m"
    return f"{prefix.lower()}_{gender}_{equip_model_id:04d}"


def resolve_preview_part_stems(
    settings: SoulstructSettings,
    stan_settings,
    *,
    female: bool,
) -> list[str] | None:
    """Resolve DSAS-order preview armor stems from EquipParamProtector XML."""
    from soulstruct.games import ELDEN_RING, NIGHTREIGN

    if settings.is_game(ELDEN_RING):
        default_rows = _ER_DEFAULT_PROTECTORS
    elif settings.is_game(NIGHTREIGN):
        default_rows = _NR_DEFAULT_PROTECTORS
    else:
        return None

    xml_path = resolve_equip_protector_xml_path(settings, stan_settings)
    if xml_path is None:
        return None

    rows = _load_xml_rows(str(xml_path), xml_path.stat().st_mtime_ns)
    stems: list[str] = []
    for slot in _DSAS_SLOT_ORDER:
        row_id = default_rows[slot]
        stem = protector_stem_for_row(rows.get(row_id, {}), female)
        if stem is not None:
            stems.append(stem)

    if not stems:
        return None
    return stems
