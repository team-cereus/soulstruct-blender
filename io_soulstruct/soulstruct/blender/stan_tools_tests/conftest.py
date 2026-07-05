"""Headless pytest bootstrap for Stan's Tools (no Blender runtime)."""

from __future__ import annotations


def pytest_configure(config):
    import sys
    from unittest.mock import MagicMock

    for _name in ("bpy", "bpy.types", "bpy.props", "bpy.ops"):
        sys.modules.setdefault(_name, MagicMock())
