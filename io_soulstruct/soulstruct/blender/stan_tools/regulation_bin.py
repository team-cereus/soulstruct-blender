"""Witchy regulation-bin param XML discovery and row loading."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from soulstruct.blender.general.properties import SoulstructSettings

_REGULATION_SUBDIRS = ("regulation-bin", "param", "param/param")
_POI_ATTACH_PARAM = "SmallBaseAndSpotAttachPoint.param.xml"


def _regulation_bin_has_poi_params(path: Path) -> bool:
    return (path / _POI_ATTACH_PARAM).is_file()


def _resolve_explicit_regulation_bin_dir(stan_settings) -> Path | None:
    if not stan_settings.regulation_bin_dir:
        return None
    path = Path(bpy.path.abspath(stan_settings.regulation_bin_dir))
    if path.is_dir():
        return path
    if path.is_file() and path.parent.is_dir():
        return path.parent
    return None


def _iter_regulation_bin_candidates(settings: SoulstructSettings) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in (settings.game_root_path, settings.project_root_path):
        if not root:
            continue
        base = Path(bpy.path.abspath(str(root)))
        for sub in _REGULATION_SUBDIRS:
            candidate = base / sub
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    return candidates


def find_regulation_bin_dir(
    settings: SoulstructSettings,
    stan_settings,
) -> Path | None:
    """Return best regulation-bin folder from override or game/project root search."""
    explicit = _resolve_explicit_regulation_bin_dir(stan_settings)
    if explicit is not None:
        return explicit

    candidates = _iter_regulation_bin_candidates(settings)
    if not candidates:
        return None

    for candidate in candidates:
        if _regulation_bin_has_poi_params(candidate):
            return candidate
    return candidates[0]


def resolve_regulation_bin_dir(
    settings: SoulstructSettings,
    stan_settings,
) -> Path | None:
    """Return regulation-bin folder from override or project/game root search."""
    return find_regulation_bin_dir(settings, stan_settings)


def auto_set_regulation_bin_dir(stan_settings, settings: SoulstructSettings) -> Path | None:
    """Set stan.regulation_bin_dir when empty and game root has a valid regulation-bin."""
    if stan_settings.regulation_bin_dir:
        return _resolve_explicit_regulation_bin_dir(stan_settings)

    if not settings.game_root_path:
        return None

    base = Path(bpy.path.abspath(str(settings.game_root_path)))
    for sub in _REGULATION_SUBDIRS:
        candidate = base / sub
        if candidate.is_dir() and _regulation_bin_has_poi_params(candidate):
            stan_settings.regulation_bin_dir = str(candidate)
            return candidate
    return None


@lru_cache(maxsize=16)
def load_param_rows(regulation_dir: str, param_stem: str, mtime_ns: int) -> dict[int, dict[str, str]]:
    """Load all rows from `<param_stem>.param.xml` as id -> attrib dict."""
    del mtime_ns
    xml_path = Path(regulation_dir) / f"{param_stem}.param.xml"
    if not xml_path.is_file():
        return {}

    rows: dict[int, dict[str, str]] = {}
    for _event, row in ET.iterparse(xml_path, events=("end",)):
        if row.tag != "row" or "id" not in row.attrib:
            continue
        try:
            row_id = int(row.attrib["id"])
        except ValueError:
            row.clear()
            continue
        rows[row_id] = dict(row.attrib)
        row.clear()
    return rows
