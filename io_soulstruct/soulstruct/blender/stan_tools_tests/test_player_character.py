from __future__ import annotations

from unittest.mock import MagicMock


# DSAS player workflow constants (mirrors player_character.py)
PLAYER_CHARACTER_STEM = "c0000"
PLAYER_COLLECTION = "Player Character"


def _is_player_character_loaded(stan_flag: bool, c0000_armature) -> bool:
    """Logic mirror of is_player_character_loaded (bpy-free)."""
    return stan_flag and c0000_armature is not None


def test_player_character_constants():
    assert PLAYER_CHARACTER_STEM == "c0000"
    assert PLAYER_COLLECTION == "Player Character"


def test_is_player_character_loaded_logic():
    assert _is_player_character_loaded(False, MagicMock()) is False
    assert _is_player_character_loaded(True, MagicMock()) is True
    assert _is_player_character_loaded(True, None) is False
    assert _is_player_character_loaded(False, None) is False
