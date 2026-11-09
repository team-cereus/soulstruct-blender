"""Keep a git-installed Soulstruct / Stan's Tools add-on up to date from inside Blender.

`installer/install.ps1` drops a stub into Blender's `scripts/startup` that calls `on_startup()`. Startup scripts run
before add-ons are enabled, so on each launch this:

1. Fast-forwards to any update that the previous session fetched (local only, no network), so the add-on loads the
   new code right away.
2. Re-runs pip if either library's `pyproject.toml` changed (new or bumped dependencies).
3. Fetches in a background thread. If a new version arrived, a popup asks the user to restart Blender.
4. On the first launch after install, enables the add-on (its first enable pip-installs the libraries).

Only fast-forwards are applied: a clone with local commits or uncommitted edits (a dev checkout) is never touched.
State lives in `.git/stan_tools_state.json` so it never shows up as a change.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import addon_utils
import bpy

ADDON_MODULE = "io_soulstruct"
LIBRARIES = ("soulstruct", "soulstruct-havok")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_update_downloaded = threading.Event()


def _log(message: str):
    print(f"[Stan's Tools updater] {message}")


def _git(repo: Path, git: str, *args: str, timeout: float = 60) -> str:
    # `core.longpaths`: soulstruct-havok's generated type modules overflow MAX_PATH under %LOCALAPPDATA%.
    # `safe.directory`: an installer run as Administrator leaves the clone owned by Administrators, not this user.
    result = subprocess.run(
        [git, "-C", str(repo), "-c", "core.longpaths=true", "-c", "safe.directory=*", *args],
        capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _is_behind(repo: Path, git: str) -> bool:
    """True when `HEAD` can fast-forward to its upstream."""
    if _git(repo, git, "rev-parse", "HEAD") == _git(repo, git, "rev-parse", "@{u}"):
        return False
    try:
        _git(repo, git, "merge-base", "--is-ancestor", "HEAD", "@{u}")
    except RuntimeError:
        return False  # local commits: not ours to move
    return True


def _load_state(repo: Path) -> dict:
    try:
        return json.loads((repo / ".git" / "stan_tools_state.json").read_text())
    except (OSError, ValueError):
        return {}


def _save_state(repo: Path, state: dict):
    # Callers hold their own copy for a while (`on_startup`, the enable timer): keep the newest update status.
    on_disk = _load_state(repo).get("update_status")
    mine = state.get("update_status")
    if on_disk and (not mine or on_disk.get("time", 0) > mine.get("time", 0)):
        state["update_status"] = on_disk
    (repo / ".git" / "stan_tools_state.json").write_text(json.dumps(state, indent=2))


def apply_pending_update(repo: Path, git: str) -> bool:
    """Fast-forward to the fetched upstream and check out matching submodules. Returns True if it updated."""
    if not _is_behind(repo, git):
        return False
    # Submodules are left out: one at another commit (e.g. an interrupted update) is put right below, and must not
    # block every later update.
    changed = _git(repo, git, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all")
    if changed:
        files = [line.split(maxsplit=1)[-1] for line in changed.splitlines()][:5]  # `_git` strips line 1
        _log(f"Update available, but {repo} has local changes ({', '.join(files)}). Skipping.")
        _record_status(repo, "blocked", f"local changes: {', '.join(files)}")
        return False
    old = _git(repo, git, "rev-parse", "--short", "HEAD")
    _git(repo, git, "merge", "--ff-only", "--quiet", "@{u}")
    _git(repo, git, "submodule", "sync", "--quiet", "--recursive")
    try:
        _git(repo, git, "submodule", "update", "--init", "--recursive", "--quiet", "--no-fetch")
    except RuntimeError:
        # The background fetch normally brings submodule commits along; download them now if it did not.
        _git(repo, git, "submodule", "update", "--init", "--recursive", "--quiet", timeout=300)
    new = _git(repo, git, "rev-parse", "--short", "HEAD")
    _log(f"Updated {old} -> {new}.")
    _record_status(repo, "updated", f"{old} -> {new}")
    return True


def _record_status(repo: Path, status: str, detail: str = ""):
    """Last update result, shown in Stan's Tools → Setup (`stan_tools/updates.py` reads it)."""
    import time

    state = _load_state(repo)
    state["update_status"] = {"status": status, "detail": detail, "time": time.time()}
    _save_state(repo, state)


def check_for_update(repo: Path, git: str) -> str:
    """Fetch now and record the result: 'available' (applied on the next Blender start), 'up_to_date', 'blocked'
    (local changes or local commits) or 'error'. Blocks for the fetch; run it off the main thread."""
    try:
        _git(repo, git, "fetch", "--quiet", "--recurse-submodules=on-demand", timeout=300)
    except Exception as ex:  # offline, GitHub down, ...
        _record_status(repo, "error", str(ex)[:200])
        return "error"
    if _git(repo, git, "rev-parse", "HEAD") == _git(repo, git, "rev-parse", "@{u}"):
        _record_status(repo, "up_to_date")
        return "up_to_date"
    if not _is_behind(repo, git):
        _record_status(repo, "blocked", "this clone has its own commits (a dev checkout?)")
        return "blocked"
    changed = _git(repo, git, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all")
    if changed:
        files = [line.split(maxsplit=1)[-1] for line in changed.splitlines()][:5]  # `_git` strips line 1
        _record_status(repo, "blocked", f"local changes: {', '.join(files)}")
        return "blocked"
    _record_status(repo, "available", _git(repo, git, "rev-parse", "--short", "@{u}"))
    return "available"


def _vendored_wheels(repo: Path) -> list[str]:
    """Wheels not on PyPI (e.g. `pyrelink`) that ship in the repo."""
    return sorted(str(p) for p in (repo / "io_soulstruct_lib" / "vendor").glob("*.whl"))


def _dependencies_hash(repo: Path) -> str:
    digest = hashlib.sha256()
    for library in LIBRARIES:
        digest.update((repo / "io_soulstruct_lib" / library / "pyproject.toml").read_bytes())
    for wheel in _vendored_wheels(repo):
        digest.update(Path(wheel).name.encode())
    return digest.hexdigest()


def sync_dependencies(repo: Path, state: dict):
    """Re-install the editable libraries when their dependencies change.

    The add-on's own first enable does the initial install, so the first time we only record the hash. Tracked per
    Blender `modules` folder, since every Blender version has its own.
    """
    modules = bpy.utils.user_resource("SCRIPTS", path="addons/modules", create=True)
    current = _dependencies_hash(repo)
    known = state.setdefault("dependencies", {})
    if known.get(modules) in (None, current):
        known[modules] = current
        return
    _log("Library dependencies changed. Updating Python packages (this can take a minute)...")
    lib = repo / "io_soulstruct_lib"
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            *_vendored_wheels(repo),
            "-e", str(lib / "soulstruct"),
            "-e", str(lib / "soulstruct-havok"),
            "--target", modules,
            "--exists-action", "i",
            "--upgrade",
            "--disable-pip-version-check",
            "--no-input",
        ],
        check=True,
    )
    known[modules] = current


def _fetch_in_background(repo: Path, git: str):
    def work():
        try:
            if check_for_update(repo, git) == "available":
                _update_downloaded.set()
        except Exception as ex:  # offline, GitHub down, ...: try again next launch
            _log(f"Update check failed: {ex}")

    thread = threading.Thread(target=work, name="stan-tools-update-check", daemon=True)
    thread.start()
    bpy.app.timers.register(lambda: _notify_when_downloaded(thread), first_interval=5.0, persistent=True)


def _notify_when_downloaded(thread: threading.Thread):
    """Timer: poll the fetch thread (bpy is not thread-safe) and tell the user once it has an update."""
    if not _update_downloaded.is_set():
        return 5.0 if thread.is_alive() else None
    window_manager = bpy.context.window_manager
    if not window_manager or not window_manager.windows:
        return 5.0

    def draw(menu, _context):
        menu.layout.label(text="An update for Stan's Tools was downloaded.")
        menu.layout.label(text="Restart Blender to use it.")

    with bpy.context.temp_override(window=window_manager.windows[0]):
        window_manager.popup_menu(draw, title="Stan's Tools", icon="INFO")
    _log("Update downloaded. Restart Blender to apply it.")
    return None


def _enable_addon_once(repo: Path, state: dict):
    """Enable the add-on on the first launch of each Blender version after install. Later toggles are the user's.

    Only a successful enable is recorded, so a first launch that fails (offline pip install, ...) retries next time.
    """
    enabled_for = state.setdefault("enabled_for", [])
    version = bpy.app.version_string
    if version in enabled_for:
        return

    def enable():
        if not bpy.context.window_manager.windows:
            return 1.0
        if not addon_utils.check(ADDON_MODULE)[1]:
            _log("Enabling the Soulstruct add-on. The first time downloads its Python packages (about a minute)...")
            addon_utils.enable(ADDON_MODULE, default_set=True, persistent=True)
            if not addon_utils.check(ADDON_MODULE)[1]:
                _log("Could not enable the add-on (see the error above). Will try again next time Blender starts.")
                return None
            try:
                bpy.ops.wm.save_userpref()
            except RuntimeError as ex:  # Blender's own preference auto-save covers this
                _log(f"Could not save preferences: {ex}")
        enabled_for.append(version)
        _save_state(repo, state)  # `on_startup` saved before this timer ran
        return None

    bpy.app.timers.register(enable, first_interval=1.0)


def on_startup(repo: Path, git: str):
    repo = Path(repo)
    state = _load_state(repo)
    state["git"] = str(git)  # for the Setup panel's 'Check for Updates' button
    try:
        try:
            apply_pending_update(repo, git)
        except Exception as ex:
            _log(f"Could not apply update: {ex}")
        sync_dependencies(repo, state)
        if not bpy.app.background:
            _enable_addon_once(repo, state)
            _fetch_in_background(repo, git)
    finally:
        _save_state(repo, state)
