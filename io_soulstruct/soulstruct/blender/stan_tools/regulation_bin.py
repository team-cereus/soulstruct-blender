"""Witchy regulation-bin param XML discovery and row loading."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from ..general.properties import SoulstructSettings

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


def _param_search_roots(settings: SoulstructSettings, stan_settings=None) -> list[Path]:
    """Mod files params (exported from the mod's regulation.bin), Project Root, Game Root, then the Unpack Folder, where
    Unpack Nightreign Files and the automatic param export write regulation-bin/ even when Project Root points
    somewhere else."""
    from .nr_unpack import mod_params_dir, nr_unpack_dir

    roots = [settings.project_root_path, settings.game_root_path]
    if settings.mod_import_root_path and (mod_reg_dir := mod_params_dir(settings.mod_import_root_path)):
        roots.insert(0, mod_reg_dir.parent)
    if stan_settings is not None:
        roots.append(nr_unpack_dir(stan_settings))
    return [Path(bpy.path.abspath(str(root))) for root in roots if root]


def find_param_xml(settings: SoulstructSettings, stan_settings, param_stem: str) -> Path | None:
    """First `<param_stem>.param.xml` in regulation-bin/, param/ or param/param/ under the search roots."""
    for root in _param_search_roots(settings, stan_settings):
        for sub in _REGULATION_SUBDIRS:
            candidate = root / sub / f"{param_stem}.param.xml"
            if candidate.is_file():
                return candidate
    return None


def _iter_regulation_bin_candidates(settings: SoulstructSettings, stan_settings=None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    roots = _param_search_roots(settings, stan_settings)
    # Game Root first, as before, so a Witchy dump next to the game still wins for POI params.
    if settings.game_root_path:
        game = Path(bpy.path.abspath(str(settings.game_root_path)))
        roots = [game] + [r for r in roots if r != game]
    for base in roots:
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

    candidates = _iter_regulation_bin_candidates(settings, stan_settings)
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
