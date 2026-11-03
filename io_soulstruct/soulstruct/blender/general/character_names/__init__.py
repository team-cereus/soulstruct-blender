"""Bundled character model id -> display name maps for search UI."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..properties import SoulstructSettings

_DIR = Path(__file__).parent

# Optional soulstruct constants fallback (JSON wins; fallback fills gaps).
_FALLBACK_MODULES: dict[str, str] = {
    "eldenring": "soulstruct.eldenring.constants",
    "darksouls1ptde": "soulstruct.darksouls1ptde.constants",
    "darksouls1r": "soulstruct.darksouls1r.constants",
    "demonssouls": "soulstruct.demonssouls.constants",
    "bloodborne": "soulstruct.bloodborne.constants",
    "darksouls3": "soulstruct.darksouls3.constants",
    "sekiro": "soulstruct.sekiro.constants",
}


@lru_cache(maxsize=None)
def _load_json(path: Path) -> dict[int, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in data.items()}


def reload_character_names() -> None:
    """Clear cached name maps (call after editing overrides)."""
    _load_json.cache_clear()


def _load_character_models_fallback(submodule_name: str) -> dict[int, str]:
    mod_path = _FALLBACK_MODULES.get(submodule_name)
    if not mod_path:
        return {}
    try:
        mod = __import__(mod_path, fromlist=["CHARACTER_MODELS"])
        return dict(mod.CHARACTER_MODELS)
    except (ImportError, AttributeError):
        pass
    return {}


def get_character_name_map(settings: SoulstructSettings) -> dict[int, str]:
    """Return model number -> display name for the active game."""
    game = settings.game
    if not game:
        return {}

    names: dict[int, str] = {}
    submodule = game.submodule_name
    names.update(_load_json(_DIR / f"{submodule}.json"))
    # Nightreign modders often keep game_enum on Elden Ring; merge NR param names too.
    if submodule == "eldenring":
        names.update(_load_json(_DIR / "nightreign.json"))
    names.update(_load_json(_DIR / "overrides.json"))

    fallback = _load_character_models_fallback(submodule)
    for model_id, display in fallback.items():
        names.setdefault(model_id, display)

    return names
