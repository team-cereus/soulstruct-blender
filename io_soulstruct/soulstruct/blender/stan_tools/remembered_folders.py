"""Remember the game / project / mod folders across Blender sessions.

Soulstruct keeps its folders in each scene, so every new .blend (and every Blender start) began empty and Nightreign
users had to run Unpack / Auto-Detect again. Those two now save the folders to `stan_tools_settings.json` in the Stan's
Tools data folder, and scenes whose folders for a game are still empty get them back on load.
"""
from __future__ import annotations

__all__ = ["remember_folders", "apply_remembered_folders", "get_recent_picks", "add_recent_pick"]

import json
import logging
from pathlib import Path

import bpy

from soulstruct.games import DARK_SOULS_DSR, get_game

from ..base.register import io_soulstruct_register, io_soulstruct_unregister
from .nr_unpack import _stan_tools_dir

_LOGGER = logging.getLogger("soulstruct.blender.stan_tools")
_MAX_RECENT_PICKS = 8
_applying = False  # filling remembered folders into a scene must not save that (maybe half-set) scene back


def _settings_path() -> Path:
    return _stan_tools_dir() / "stan_tools_settings.json"


def _load() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict):
    try:
        _settings_path().parent.mkdir(parents=True, exist_ok=True)
        _settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as ex:
        _LOGGER.warning(f"Could not save Stan's Tools settings to {_settings_path()}: {ex}")


def get_recent_picks(key: str) -> list[str]:
    return _load().get("recent_picks", {}).get(key, [])


def add_recent_pick(key: str, value: str):
    data = _load()
    recent = data.setdefault("recent_picks", {}).setdefault(key, [])
    data["recent_picks"][key] = [value, *(v for v in recent if v != value)][:_MAX_RECENT_PICKS]
    _save(data)


def remember_folders(context: bpy.types.Context):
    """Save the active game's folders (called after Unpack Nightreign Files and Auto-Detect)."""
    if _applying:
        return
    settings = context.scene.soulstruct_settings
    game = settings.game
    if not game:
        return
    game_settings = settings.game_settings
    data = _load()
    data["game"] = game.variable_name
    data.setdefault("games", {})[game.variable_name] = {
        "game_root": game_settings.game_root_str,
        "project_root": game_settings.project_root_str,
        "mod_root": game_settings.mod_root_str,
        "mod_import_root": game_settings.mod_import_root_str,
        "prefer_import_from_project": settings.prefer_import_from_project,
        "nightreign_unpack_staging": settings.nightreign_unpack_staging_str,
    }
    _save(data)


def apply_remembered_folders(scene: bpy.types.Scene) -> bool:
    """Fill remembered folders into games whose folders are all empty in `scene`. Never overwrites a set folder."""
    global _applying
    _applying = True
    try:
        return _apply_remembered_folders(scene)
    finally:
        _applying = False


def _apply_remembered_folders(scene: bpy.types.Scene) -> bool:
    data = _load()
    settings = scene.soulstruct_settings
    untouched_scene = (
        settings.game_enum == DARK_SOULS_DSR.variable_name and not settings.game_settings.game_root_str
        and not settings.game_settings.project_root_str
    )
    applied = False
    for game_name, folders in data.get("games", {}).items():
        try:
            game_settings = getattr(settings, get_game(game_name).submodule_name)
        except (KeyError, ValueError, AttributeError):
            continue
        if not game_settings.mod_import_root_str:
            # Added later than the other folders: saved setups without it get an installed Eclipse found once.
            mod_import = folders.get("mod_import_root")
            if mod_import is None and game_name == "NIGHTREIGN":
                from .steam_paths import detect_eclipse_mod_dir
                detected = detect_eclipse_mod_dir()
                mod_import = str(detected) if detected else ""
                folders["mod_import_root"] = mod_import
                _save(data)  # detect once; clearing the field afterwards sticks
            if mod_import:
                game_settings.mod_import_root_str = mod_import
                applied = True
        if game_settings.game_root_str or game_settings.project_root_str or game_settings.mod_root_str:
            continue  # this scene has its own folders for that game
        game_settings.game_root_str = folders.get("game_root", "")
        game_settings.project_root_str = folders.get("project_root", "")
        game_settings.mod_root_str = folders.get("mod_root", "")
        if game_name == data.get("game"):
            settings.prefer_import_from_project = folders.get("prefer_import_from_project", True)
            if not settings.nightreign_unpack_staging_str:
                settings.nightreign_unpack_staging_str = folders.get("nightreign_unpack_staging", "")
        applied = True
    if applied and untouched_scene and data.get("game"):
        settings.game_enum = data["game"]  # a fresh default scene: open on the game you last set up

    # No saved Nightreign folders at all (never ran Unpack / Auto-Detect): still find an installed Eclipse, once.
    nightreign = settings.nightreign
    if "NIGHTREIGN" not in data.get("games", {}) and not nightreign.mod_import_root_str and not data.get("eclipse_checked"):
        from .steam_paths import detect_eclipse_mod_dir

        data["eclipse_checked"] = True
        _save(data)
        if detected := detect_eclipse_mod_dir():
            nightreign.mod_import_root_str = str(detected)
            data.setdefault("games", {})["NIGHTREIGN"] = {"mod_import_root": str(detected)}
            _save(data)
            applied = True
    return applied


@bpy.app.handlers.persistent
def _apply_to_all_scenes(_dummy=None):
    for scene in bpy.data.scenes:
        try:
            apply_remembered_folders(scene)
        except Exception as ex:  # never break file loading
            _LOGGER.warning(f"Could not restore remembered Stan's Tools folders: {ex}")


@io_soulstruct_register
def _register_remembered_folders():
    bpy.app.handlers.load_post.append(_apply_to_all_scenes)
    # `load_post` does not fire for the file already open when the add-on loads (e.g. at Blender start).
    bpy.app.timers.register(lambda: _apply_to_all_scenes() and None, first_interval=0.5)


@io_soulstruct_unregister
def _unregister_remembered_folders():
    if _apply_to_all_scenes in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_apply_to_all_scenes)
