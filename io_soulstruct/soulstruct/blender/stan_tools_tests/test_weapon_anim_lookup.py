from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

from soulstruct.eldenring.containers import DivBinder

_HKX_ENTRY_RE = re.compile(r"^a.*\.hkx(\.dcx)?$", re.IGNORECASE)
_ER_DLC_ANIBND_STEMS = ("c0000_dlc01", "c0000_dlc02")
_C0000_ANIBND_GLOB = "c0000*.anibnd*"


def _load_weapon_attack_slots():
    path = Path(__file__).resolve().parents[1] / "stan_tools" / "weapon_attack_slots.py"
    qual = "stan_tools_weapon_attack_slots_integration"
    spec = importlib.util.spec_from_file_location(qual, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)
    return mod


_was = _load_weapon_attack_slots()
HAND_OFFSET_RH = _was.HAND_OFFSET_RH
attack_hkx_stem = _was.attack_hkx_stem
anim_id_to_binder_entry_id = _was.anim_id_to_binder_entry_id


def _discover_chr_c0000_anibnd_stems(settings) -> list[str]:
    stems: list[str] = []
    seen: set[str] = set()
    try:
        chr_dir = settings.get_import_dir_path("chr")
    except (NotADirectoryError, FileNotFoundError):
        return stems
    for path in sorted(chr_dir.glob(_C0000_ANIBND_GLOB)):
        if not path.is_file():
            continue
        stem = path.name.split(".")[0].lower()
        if stem not in seen:
            seen.add(stem)
            stems.append(stem)
    return stems


def _list_c0000_sub_anibnd_stems(settings) -> list[str]:
    stems: list[str] = []
    seen: set[str] = set()
    relative_anibnd_path = Path("chr") / "c0000.anibnd.dcx"
    anibnd_path = settings.get_import_file_path(relative_anibnd_path)
    if anibnd_path and anibnd_path.is_file():
        try:
            anibnd = DivBinder.from_path(anibnd_path)
            for entry in anibnd.find_entries_matching_name(r"c0000_.*\.txt"):
                if entry.stem not in seen:
                    seen.add(entry.stem)
                    stems.append(entry.stem)
        except Exception:
            pass
    for dlc_stem in _ER_DLC_ANIBND_STEMS:
        dlc_path = settings.get_import_file_path(Path("chr") / f"{dlc_stem}.anibnd.dcx")
        if dlc_path and dlc_path.is_file() and dlc_stem not in seen:
            seen.add(dlc_stem)
            stems.append(dlc_stem)
    for stem in _discover_chr_c0000_anibnd_stems(settings):
        if stem not in seen:
            seen.add(stem)
            stems.append(stem)
    return sorted(stems)


def find_attack_animation_entry(settings, sub_anibnd_stem: str, anim_stem: str):
    stems_to_try: list[str] = []
    seen: set[str] = set()

    def _add(stem: str) -> None:
        if stem and stem not in seen:
            seen.add(stem)
            stems_to_try.append(stem)

    _add(sub_anibnd_stem)
    for stem in _list_c0000_sub_anibnd_stems(settings):
        _add(stem)
    for stem in _discover_chr_c0000_anibnd_stems(settings):
        _add(stem)

    anim_lower = anim_stem.lower()
    for stem in stems_to_try:
        sub_path = settings.get_import_file_path(Path("chr") / f"{stem}.anibnd.dcx")
        if not sub_path or not sub_path.is_file():
            continue
        try:
            anibnd = DivBinder.from_path(sub_path)
        except Exception:
            continue
        for entry in anibnd.entries:
            if entry.stem.lower() == anim_lower and _HKX_ENTRY_RE.match(entry.name):
                return anibnd, entry
        try:
            suffix = anim_stem.split("_", 1)[1]
            entry_id = anim_id_to_binder_entry_id(int(suffix))
            entry = anibnd[entry_id]
            if _HKX_ENTRY_RE.match(entry.name):
                return anibnd, entry
        except (KeyError, TypeError, ValueError, IndexError):
            pass
    return None


def _er_game_root() -> Path | None:
    env = os.environ.get("ER_GAME_ROOT")
    if env:
        root = Path(env)
        if root.is_dir():
            return root
    default = Path(r"S:/SteamLibrary/steamapps/common/ELDEN RING/Game")
    return default if default.is_dir() else None


class _ErSettings:
    game = "ELDEN_RING"

    def __init__(self, game_root: Path):
        self.game_root_path = game_root
        self.project_root_path = None
        self.import_roots = []

    def get_import_file_path(self, relative_path: Path) -> Path | None:
        candidate = self.game_root_path / relative_path
        if candidate.is_file():
            return candidate
        if not str(relative_path).endswith(".dcx"):
            dcx = Path(str(relative_path) + ".dcx")
            candidate = self.game_root_path / dcx
            if candidate.is_file():
                return candidate
        return None

    def get_import_dir_path(self, subdir: str) -> Path:
        path = self.game_root_path / subdir
        if not path.is_dir():
            raise NotADirectoryError(subdir)
        return path

    def is_er_family(self) -> bool:
        return True


@pytest.fixture
def er_settings():
    game_root = _er_game_root()
    if game_root is None:
        pytest.skip("ER game root not found (set ER_GAME_ROOT or install Elden Ring)")
    return _ErSettings(game_root)


def test_find_backhand_blade_light_rh_in_dlc02(er_settings):
    anim_stem = attack_hkx_stem(58, HAND_OFFSET_RH, 0, er_family=True)
    assert anim_stem == "a058_030000"
    found = find_attack_animation_entry(er_settings, "c0000_a00", anim_stem)
    assert found is not None, f"{anim_stem} not found in any c0000 ANIBND"
    anibnd, entry = found
    assert "dlc02" in anibnd.path.name.lower() or entry.stem.lower() == anim_stem
