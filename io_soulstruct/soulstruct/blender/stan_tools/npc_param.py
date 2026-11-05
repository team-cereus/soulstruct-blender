"""NpcParam draw-mask loading and FLVER mesh visibility (DSAS-style NPC Param Selection)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from ..general.properties import SoulstructSettings

DRAW_MASK_COUNT = 32
_MASK_FIELD_RE = re.compile(r"^modelDisp(?:lay)?Mask(\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NpcParamVariant:
    row_id: int
    label: str
    draw_mask: tuple[bool, ...]
    behavior_variation_id: int


def npc_row_chr_id(row_id: int) -> int:
    """ER/NR: character model id embedded in NpcParam row id."""
    return (row_id % 100_000_000) // 10_000


def _draw_mask_from_row_attrib(attrib: dict[str, str]) -> tuple[bool, ...]:
    mask = [False] * DRAW_MASK_COUNT
    for key, value in attrib.items():
        match = _MASK_FIELD_RE.match(key)
        if not match:
            continue
        idx = int(match.group(1))
        if 0 <= idx < DRAW_MASK_COUNT:
            mask[idx] = value in {"1", "true", "True"}
    return tuple(mask)


def _resolve_npc_param_xml_path(
    settings: SoulstructSettings,
    stan_tools_settings,
) -> Path | None:
    stan = stan_tools_settings
    if stan.npc_param_xml_path:
        path = Path(bpy.path.abspath(stan.npc_param_xml_path))
        if path.is_file():
            return path

    from .regulation_bin import find_param_xml

    return find_param_xml(settings, stan, "NpcParam")


@lru_cache(maxsize=4)
def _load_variants_by_chr_id(xml_path: str, mtime_ns: int) -> dict[int, list[NpcParamVariant]]:
    del mtime_ns  # cache key only
    by_chr: dict[int, list[NpcParamVariant]] = {}
    path = Path(xml_path)
    for _event, row in ET.iterparse(path, events=("end",)):
        if row.tag != "row" or "id" not in row.attrib:
            continue
        try:
            row_id = int(row.attrib["id"])
        except ValueError:
            row.clear()
            continue

        try:
            behavior = int(row.attrib.get("behaviorVariationId", row.attrib.get("behaviorVariationID", "0")))
        except ValueError:
            behavior = 0

        draw_mask = _draw_mask_from_row_attrib(row.attrib)
        chr_id = npc_row_chr_id(row_id)
        label = f"{row_id} (var {behavior})"
        by_chr.setdefault(chr_id, []).append(
            NpcParamVariant(row_id=row_id, label=label, draw_mask=draw_mask, behavior_variation_id=behavior)
        )
        row.clear()

    for variants in by_chr.values():
        variants.sort(key=lambda v: v.row_id)
    return by_chr


def get_npc_param_variants_for_model(
    settings: SoulstructSettings,
    stan_tools_settings,
    model_stem: str,
) -> list[NpcParamVariant]:
    """Return NpcParam rows for a character model (e.g. c7720 -> chr id 7720)."""
    if not model_stem.startswith("c") or len(model_stem) < 5:
        return []
    try:
        chr_id = int(model_stem[1:5])
    except ValueError:
        return []

    xml_path = _resolve_npc_param_xml_path(settings, stan_tools_settings)
    if xml_path is None:
        return []

    index = _load_variants_by_chr_id(str(xml_path), xml_path.stat().st_mtime_ns)
    return list(index.get(chr_id, []))


def find_character_armature(context: bpy.types.Context, model_stem: str) -> bpy.types.Object | None:
    model_lower = model_stem.lower()
    if context.active_object and context.active_object.type == "ARMATURE":
        if context.active_object.name.lower().startswith(model_lower):
            return context.active_object
    for obj in context.scene.objects:
        if obj.type == "ARMATURE" and obj.name.lower().startswith(model_lower):
            return obj
    return None
