"""Blender add-ons for importing/export formats from FromSoftware games and manipulating their data.

Primarily tested and maintained for Dark Souls Remastered. See README.md for table of supported games and file types.

team-cereus fork: installed as a regular add-on (`scripts/addons/io_soulstruct` + `io_soulstruct_lib`), not as
upstream's wheel-based Blender Extension, so the fork's own `soulstruct` / `soulstruct-havok` libraries (Elden Ring /
Nightreign work) are used instead of the PyPI releases. On first enable, those libraries are pip-installed (editable)
from `io_soulstruct_lib` into Blender's user `addons/modules` folder. See `installer/README.md`.
"""
from __future__ import annotations

import importlib
import importlib.util
import site
import subprocess
import sys
from pathlib import Path

try:
    import bpy
except ModuleNotFoundError:
    raise ModuleNotFoundError(
        "This module requires Blender (`bpy`, etc.) to be run in order to import it. "
        "Please ensure you are running this code inside Blender's Python environment."
    )

user_addon_modules = bpy.utils.user_resource("SCRIPTS", path="addons/modules")
# Make sure editable `soulstruct` and `soulstruct-havok` modules are found.
site.addsitedir(user_addon_modules)


def _ensure_soulstruct_installed():
    """Check that required modules are available."""

    try:
        import soulstruct.base
        import soulstruct.havok
        import pyrelink
    except ImportError as ex:
        # Reintall below.
        print(f"Import error: {ex}")
        print(
            "Could not detect `soulstruct` and/or `soulstruct-havok` modules in Blender's Python environment. "
            "Will reinstall now to Blender's local user 'scripts/addons/modules' folder."
        )
    else:
        return

    # Install editable `soulstruct` and `soulstruct-havok` modules into Python environment from `io_soulstruct_lib`.
    io_soulstruct_lib_path = (Path(__file__).parent / "../io_soulstruct_lib").resolve()

    if not io_soulstruct_lib_path.is_dir():
        raise ImportError(
            f"Cannot find `io_soulstruct_lib` directory at {io_soulstruct_lib_path} to install `soulstruct`. "
            "Please ensure that the add-on is installed correctly."
        )

    print("Pip-installing editable `soulstruct` and `soulstruct-havok` modules into Blender's Python environment...")

    def _call_python_module(purpose: str, *args: str):
        try:
            subprocess.run([sys.executable, "-m", *args], stdout=sys.stdout, stderr=sys.stderr, check=True)
        except subprocess.CalledProcessError as _ex:
            print(_ex.stdout)
            print(_ex.stderr)
            raise RuntimeError(f"Failed to {purpose} in Blender Python. Error: {_ex}") from _ex

    # `pyrelink` (used by the add-on itself) is not on PyPI; upstream bundles it in its Extension, we vendor it.
    vendored_wheels = sorted(str(p) for p in (io_soulstruct_lib_path / "vendor").glob("*.whl"))

    _call_python_module("call `ensurepip`", "ensurepip")
    _call_python_module("upgrade `pip`", "pip", "install", "--upgrade", "pip")
    _call_python_module(
        "install `soulstruct` and its dependencies",
        "pip", "install",
            *vendored_wheels,
            "-e", f"{io_soulstruct_lib_path}/soulstruct",
            "-e", f"{io_soulstruct_lib_path}/soulstruct-havok",
            "--target", user_addon_modules,
            "--upgrade",  # replace stale packages already in `--target` (e.g. an older pinned scipy)
    )

    print("Installed `soulstruct` and `soulstruct-havok` modules into Blender's Python environment.")

    # Find editable installs.
    site.addsitedir(user_addon_modules)
    # Force importlib's pathfinders to check modules again.
    importlib.invalidate_caches()

    try:
        import soulstruct.base
        import soulstruct.havok
        import pyrelink
    except ImportError as ex:
        raise ImportError(
            "Required modules 'soulstruct', 'soulstruct-havok' and 'pyrelink' could not be imported, even after "
            "attempted install. "
            "Please ensure they are installed in Blender's Python environment (in user's local `modules`). "
            "Restarting Blender and trying again may also fix this."
        ) from ex


_ensure_soulstruct_installed()


# Reload all Soulstruct modules, then all modules in this add-on (except this script).
# NOTE: This is IMPORTANT when using 'Reload Scripts' in Blender, as it is otherwise prone to partial re-imports of
# Soulstruct that duplicate classes and cause wild bugs with `isinstance`, object ID equality, etc.

def _try_reload(_module_name: str):
    try:
        importlib.reload(sys.modules[_module_name])
    except (KeyError, ImportError):
        pass


for module_name in list(sys.modules.keys()):
    if "soulstruct.blender" in module_name:
        _try_reload(module_name)


from .soulstruct.blender.base.register import register_io_soulstruct, unregister_io_soulstruct
from .soulstruct.blender.general.properties import try_load_oodle_dll_for_all_scenes

from .soulstruct.blender.misc import *

from .soulstruct.blender.animation import *
from .soulstruct.blender.collision import *
from .soulstruct.blender.cutscene import *
from .soulstruct.blender.flver import *
from .soulstruct.blender.nav_graph import *
from .soulstruct.blender.navmesh import *
from .soulstruct.blender import stan_tools  # noqa: F401 (registers via decorators)


bl_info = {
    "name": "Soulstruct",
    "author": "Scott Mooney (Grimrukh)",
    "version": (3, 2, 1),  # SOURCE OF TRUTH
    "blender": (5, 1, 0),  # MINIMUM SUPPORTED VERSION
    "location": "File > Import-Export",
    "description": "Import, manipulate, and export FromSoftware/Havok assets",
    "warning": "",
    "doc_url": "https://github.com/Grimrukh/soulstruct-blender",
    "support": "COMMUNITY",
    "category": "Import-Export",
}


# TODO: Add more operators to menu functions.


# noinspection PyUnusedLocal
def menu_func_import(self, context):
    layout = self.layout
    layout.operator(ImportFLVER.bl_idname, text="FLVER (.flver/.*bnd)")
    layout.operator(ImportAnyNVM.bl_idname, text="NVM (.nvm/.nvmbnd)")
    layout.operator(ImportAnyMCG.bl_idname, text="MCG (.mcg)")


# noinspection PyUnusedLocal
def menu_func_export(self, context):
    layout = self.layout
    layout.operator(ExportAnyFLVER.bl_idname, text="FLVER (.flver)")
    layout.operator(ExportFLVERIntoAnyBinder.bl_idname, text="FLVER to Binder (.*bnd)")
    layout.operator(ExportAnyNVM.bl_idname, text="NVM (.nvm)")
    layout.operator(ExportNVMIntoAnyBinder.bl_idname, text="NVM to Binder (.nvmbnd)")


# noinspection PyUnusedLocal
def menu_func_view3d_mt(self, context):
    layout = self.layout
    layout.operator(CopyMeshSelectionOperator.bl_idname, text="Copy Mesh Selection to Mesh")


# noinspection PyUnusedLocal
def havok_menu_func_import(self, context):
    self.layout.operator(ImportAnyHKXMapCollision.bl_idname, text="HKX Collision (.hkx/.hkxbhd)")
    self.layout.operator(ImportAnyHKXAnimation.bl_idname, text="HKX Animation (.hkx/.hkxbhd)")
    self.layout.operator(ImportHKXCutscene.bl_idname, text="HKX Cutscene (.remobnd)")


# noinspection PyUnusedLocal
def havok_menu_func_export(self, context):
    self.layout.operator(ExportAnyHKXMapCollision.bl_idname, text="HKX Collision (.hkx)")
    self.layout.operator(ExportHKXMapCollisionIntoAnyBinder.bl_idname, text="HKX Collision to Binder (.hkxbhd)")
    self.layout.operator(ExportAnyHKXAnimation.bl_idname, text="HKX Animation (.hkx)")
    self.layout.operator(ExportHKXAnimationIntoAnyBinder.bl_idname, text="HKX Animation to Binder (.hkxbhd)")
    self.layout.operator(ExportHKXCutscene.bl_idname, text="HKX Cutscene (.remobnd)")


# TODO: Put all Scene pointer props under a common group like `Scene.soulstruct`.


def register():

    register_io_soulstruct()

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.VIEW3D_MT_object.append(menu_func_view3d_mt)

    bpy.types.TOPBAR_MT_file_import.append(havok_menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(havok_menu_func_export)

    bpy.app.handlers.load_post.append(try_load_oodle_dll_for_all_scenes)

    # `bpy.data` is restricted during add-on registration, so read the scene setting once registration is done.
    bpy.app.timers.register(_apply_stan_tools_file_logging, first_interval=0.1)


def _apply_stan_tools_file_logging():
    from .soulstruct.blender.stan_tools.debug_log import ensure_stan_tools_file_logging

    for scene in bpy.data.scenes:
        if getattr(scene, "soulstruct_settings", None) is not None:
            ensure_stan_tools_file_logging(scene.soulstruct_settings.enable_debug_logging)
            break
    return None


def unregister():

    bpy.app.handlers.load_post.remove(try_load_oodle_dll_for_all_scenes)

    from .soulstruct.blender.stan_tools.debug_log import ensure_stan_tools_file_logging

    ensure_stan_tools_file_logging(False)
    unregister_io_soulstruct()

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.VIEW3D_MT_object.remove(menu_func_view3d_mt)
    bpy.types.TOPBAR_MT_file_import.remove(havok_menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(havok_menu_func_export)


if __name__ == "__main__":
    register()
