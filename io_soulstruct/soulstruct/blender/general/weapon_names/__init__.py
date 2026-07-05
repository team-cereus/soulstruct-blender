"""Bundled EquipParamWeapon row metadata for Stan's Tools weapon search."""

from __future__ import annotations



import json

from functools import lru_cache

from pathlib import Path

from typing import TYPE_CHECKING, TypedDict



if TYPE_CHECKING:

    from soulstruct.blender.general.properties import SoulstructSettings



_DIR = Path(__file__).parent



_FALLBACK_MODULES: dict[str, str] = {

    "darksouls1ptde": "soulstruct.darksouls1ptde.constants",

    "darksouls1r": "soulstruct.darksouls1r.constants",

}





class WeaponIndexEntry(TypedDict):

    name: str

    equipModelId: int

    stem: str

    wepmotionCategory: int

    weaponCategory: int





def _infer_wepmotion(equip_id: int) -> int:

    if equip_id in {208, 251, 402, 450, 451, 452}:

        return {208: 26, 251: 26, 402: 29, 450: 29, 451: 29, 452: 29}[equip_id]

    ranges = [

        (100, 119, 20), (266, 274, 25), (270, 281, 26), (300, 302, 27),

        (400, 406, 28), (450, 452, 29), (500, 503, 30), (504, 510, 32),

        (200, 299, 23), (600, 699, 35), (700, 799, 37), (800, 899, 33),

        (900, 999, 34),

    ]

    for low, high, cat in ranges:

        if low <= equip_id <= high:

            return cat

    return 23





@lru_cache(maxsize=None)

def _load_json(path: Path) -> dict[int, WeaponIndexEntry]:

    if not path.is_file():

        return {}

    data = json.loads(path.read_text(encoding="utf-8"))

    result: dict[int, WeaponIndexEntry] = {}

    for key, row in data.items():

        try:

            row_id = int(key)

        except ValueError:

            continue

        if isinstance(row, dict):

            result[row_id] = row  # type: ignore[assignment]

    return result





def reload_weapon_names() -> None:

    """Clear cached weapon maps (call after editing overrides)."""

    _load_json.cache_clear()





def _load_weapon_models_fallback(submodule_name: str) -> dict[int, WeaponIndexEntry]:

    mod_path = _FALLBACK_MODULES.get(submodule_name)

    if not mod_path:

        return {}

    try:

        mod = __import__(mod_path, fromlist=["WEAPON_MODELS"])

        models = mod.WEAPON_MODELS

    except (ImportError, AttributeError):

        return {}



    fallback: dict[int, WeaponIndexEntry] = {}

    for equip_id, name in models.items():

        if equip_id <= 0:

            continue

        row_id = equip_id * 1000

        fallback[row_id] = {

            "name": name,

            "equipModelId": equip_id,

            "stem": f"WP_A_{equip_id:04d}",

            "wepmotionCategory": _infer_wepmotion(equip_id),

            "weaponCategory": 0,

        }

    return fallback





def get_weapon_index(settings: SoulstructSettings) -> dict[int, WeaponIndexEntry]:

    """Return EquipParamWeapon row id -> weapon metadata for the active game."""

    game = settings.game

    if not game:

        return {}



    weapons: dict[int, WeaponIndexEntry] = {}

    submodule = game.submodule_name

    weapons.update(_load_json(_DIR / f"{submodule}.json"))

    if submodule == "eldenring":

        weapons.update(_load_json(_DIR / "nightreign.json"))

    if submodule in ("eldenring", "nightreign"):

        er_all = _load_json(_DIR / "eldenring.json")

        for row_id, entry in er_all.items():

            if row_id >= 64000000:

                weapons[row_id] = entry

    weapons.update(_load_json(_DIR / "overrides.json"))



    fallback = _load_weapon_models_fallback(submodule)

    for row_id, entry in fallback.items():

        weapons.setdefault(row_id, entry)



    return weapons


