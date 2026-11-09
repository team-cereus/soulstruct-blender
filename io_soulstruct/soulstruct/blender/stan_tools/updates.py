"""Stan's Tools version, the installed commit, and the auto-updater's status for the Setup panel.

Installs made by `installer/install.ps1` are git clones that `installer/stan_tools_updater.py` fast-forwards on
Blender start. It records its last result in `.git/stan_tools_state.json`, shown here, and 'Check for Updates' runs
its check on demand.
"""
from __future__ import annotations

__all__ = ["STAN_TOOLS_VERSION", "StanCheckForUpdates", "draw_update_status", "version_label"]

import importlib.util
import json
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

import bpy

from ..base.operators import LoggingOperator
from ..base.register import io_soulstruct_operator
from .version import STAN_TOOLS_VERSION

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_check_thread: threading.Thread | None = None


@lru_cache(maxsize=1)
def _repo() -> Path | None:
    """The git clone the add-on runs from (the installer links Blender's add-on folder into it), or None."""
    try:
        root = Path(__file__).resolve().parents[4]  # .../<repo>/io_soulstruct/soulstruct/blender/stan_tools
    except (OSError, IndexError):
        return None
    return root if (root / ".git").exists() and (root / "installer" / "stan_tools_updater.py").is_file() else None


def _state() -> dict:
    repo = _repo()
    if repo is None:
        return {}
    try:
        return json.loads((repo / ".git" / "stan_tools_state.json").read_text())
    except (OSError, ValueError):
        return {}


def _git_exe() -> str:
    return _state().get("git") or "git"


@lru_cache(maxsize=4)
def _commit(head_mtime_ns: int) -> str:
    del head_mtime_ns
    repo = _repo()
    if repo is None:
        return ""
    try:
        result = subprocess.run(
            [_git_exe(), "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def version_label() -> str:
    """'Stan's Tools 1.0.0 (2b07b31)'; the commit is left out when not running from a git clone."""
    repo = _repo()
    commit = ""
    if repo is not None:
        try:
            commit = _commit((repo / ".git" / "HEAD").stat().st_mtime_ns + (repo / ".git" / "index").stat().st_mtime_ns)
        except OSError:
            commit = _commit(0)
    return f"Stan's Tools {STAN_TOOLS_VERSION}" + (f" ({commit})" if commit else "")


_STATUS_TEXT = {
    "up_to_date": ("Up to date", "CHECKMARK"),
    "available": ("Update downloaded: restart Blender to use it", "IMPORT"),
    "updated": ("Updated on this start", "CHECKMARK"),
    "blocked": ("Auto-update is off", "ERROR"),
    "error": ("Update check failed", "ERROR"),
}


def draw_update_status(layout):
    box = layout.box()
    row = box.row()
    row.label(text=version_label(), icon="TOOL_SETTINGS")
    if _repo() is not None:
        row.operator(StanCheckForUpdates.bl_idname, text="", icon="FILE_REFRESH")
    else:
        box.label(text="Not installed with the Stan's Tools installer: no auto-update.", icon="INFO")
        return
    if _check_thread is not None and _check_thread.is_alive():
        box.label(text="Checking for updates...", icon="TIME")
        return
    status = _state().get("update_status")
    if not status:
        box.label(text="Updates are checked each time Blender starts.", icon="INFO")
        return
    text, icon = _STATUS_TEXT.get(status.get("status"), (status.get("status", "?"), "INFO"))
    minutes = (time.time() - status.get("time", time.time())) / 60
    when = "just now" if minutes < 1 else f"{minutes:.0f} min ago" if minutes < 120 else f"{minutes / 60:.0f} h ago"
    box.label(text=f"{text} ({when})", icon=icon)
    if detail := status.get("detail"):
        if status.get("status") in ("blocked", "error"):
            box.label(text=detail[:120])


def _load_updater(repo: Path):
    spec = importlib.util.spec_from_file_location("stan_tools_updater_check", repo / "installer" / "stan_tools_updater.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@io_soulstruct_operator
class StanCheckForUpdates(LoggingOperator):
    bl_idname = "stan_tools.check_for_updates"
    bl_label = "Check for Updates"
    bl_description = (
        "Look for a new Stan's Tools version now. A downloaded update is applied the next time Blender starts"
    )

    def execute(self, context):
        global _check_thread
        repo = _repo()
        if repo is None:
            return self.error("Stan's Tools was not installed with its installer, so it cannot update itself.")
        if _check_thread is not None and _check_thread.is_alive():
            return {"FINISHED"}
        updater = _load_updater(repo)
        git = _git_exe()
        result = {}

        def work():
            try:
                result["status"] = updater.check_for_update(repo, git)
            except Exception as ex:  # noqa: BLE001
                result["status"] = f"error: {ex}"

        _check_thread = threading.Thread(target=work, name="stan-tools-check-for-updates", daemon=True)
        _check_thread.start()

        def poll():
            if _check_thread.is_alive():
                _redraw()
                return 0.5
            _redraw()
            if result.get("status") == "available":
                _popup("An update was downloaded. Restart Blender to use it.")
            elif result.get("status") == "up_to_date":
                _popup("Stan's Tools is up to date.")
            return None

        bpy.app.timers.register(poll, first_interval=0.5)
        return {"FINISHED"}


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _popup(message: str):
    window_manager = bpy.context.window_manager
    if not window_manager.windows:
        return

    def draw(menu, _context):
        menu.layout.label(text=message)

    with bpy.context.temp_override(window=window_manager.windows[0]):
        window_manager.popup_menu(draw, title="Stan's Tools", icon="INFO")
