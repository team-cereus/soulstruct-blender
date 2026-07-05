from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(name: str, filename: str):
    path = Path(__file__).resolve().parents[1] / "stan_tools" / filename
    qual = f"stan_tools_{name}_test"
    spec = importlib.util.spec_from_file_location(qual, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)
    return mod


_wap = _load_module("wep_absorp_param", "wep_absorp_param.py")
route_global_dummy_id = _wap.route_global_dummy_id


def test_route_global_dummy_id_body_local():
    assert route_global_dummy_id(279) == (0, 279)


def test_route_global_dummy_id_right_weapon_manager():
    assert route_global_dummy_id(10279) == (10, 279)


def test_route_global_dummy_id_left_weapon_manager():
    assert route_global_dummy_id(20015) == (20, 15)


def test_route_global_dummy_id_invalid():
    assert route_global_dummy_id(-1) == (-1, -1)
    assert route_global_dummy_id(None) == (-1, -1)


def test_route_global_dummy_id_boundary_below_1000():
    assert route_global_dummy_id(999) == (0, 999)


def test_route_global_dummy_id_boundary_at_1000():
    assert route_global_dummy_id(1000) == (1, 0)
