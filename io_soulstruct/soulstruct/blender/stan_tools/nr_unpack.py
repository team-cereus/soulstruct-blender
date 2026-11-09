"""One-click Nightreign unpack for people without a UXM-unpacked game.

Downloads `NrUnpack.exe` (source: `tools/nr-unpack`, published as a GitHub release of this repo), checks its SHA-256,
then extracts the chosen archive folders from the Steam install into a separate folder that becomes the Project
Root. The game folder is only read: nothing is patched, so the game stays playable online.
"""
from __future__ import annotations

__all__ = [
    "StanUnpackNightreign",
    "default_unpack_dir",
    "ensure_nightreign_params",
    "mod_params_dir",
    "mod_params_status",
    "nr_unpack_dir",
    "unpack_status",
]

import hashlib
import os
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

import bpy

from soulstruct.games import NIGHTREIGN

from ..base.operators import LoggingOperator
from ..base.register import io_soulstruct_operator
from ..general.matdefs import clear_cached_matdefs
from ..general.properties import SoulstructSettings
from .steam_paths import detect_game_root

UNPACKER_VERSION = "1.2.0"
UNPACKER_URL = (
    "https://github.com/team-cereus/soulstruct-blender/releases/download/"
    f"nr-unpack-v{UNPACKER_VERSION}/NrUnpack.exe"
)
UNPACKER_SHA256 = "42a69086a13e2f6557af855cf6aa847f5f2e5ea283fe7cc35840172678e37d4f"
_FREE_SPACE_MARGIN = 512 * 1024**2
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _stan_tools_dir() -> Path:
    """Stan's Tools data folder (unpacker download, default unpack folder). `STAN_TOOLS_DATA_DIR` moves it, e.g. off
    a full C: drive; otherwise %LOCALAPPDATA%/StanTools."""
    if data_dir := os.environ.get("STAN_TOOLS_DATA_DIR"):
        return Path(data_dir)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "StanTools"


def default_unpack_dir() -> Path:
    return _stan_tools_dir() / "nr-unpack"


def nr_unpack_dir(stan) -> Path:
    """The Unpack Folder setting, or the default one."""
    return Path(bpy.path.abspath(stan.nr_unpack_dir)) if stan.nr_unpack_dir else default_unpack_dir()


# Game roots whose automatic param export already ran (or failed) this Blender session, so a failure is not retried on
# every import.
_PARAMS_TRIED: set[Path] = set()


def export_params(game_root: Path, out_dir: Path, job: _UnpackJob | None = None) -> Path:
    """Write `out_dir/regulation-bin/*.param.xml` from the game's regulation.bin, without extracting any archive files.
    Blocks for a few seconds (plus a one-time 40 MB unpacker download). Raises RuntimeError on failure."""
    exe = _ensure_unpacker(job or _UnpackJob())
    out_dir.mkdir(parents=True, exist_ok=True)
    # NrUnpack needs an --include; this prefix matches no archive file, so only the params are written.
    args = [str(exe), "--game", str(game_root), "--out", str(out_dir), "--include", "__params_only__/", "--params"]
    result = subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=600)
    reg_dir = out_dir / "regulation-bin"
    if result.returncode != 0 or not (reg_dir / "NpcParam.param.xml").is_file():
        lines = [line for line in (result.stderr + result.stdout).splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else f"Param export failed (exit {result.returncode}).")
    return reg_dir


def ensure_nightreign_params(context) -> Path | None:
    """Nightreign only: export regulation-bin/*.param.xml into the Unpack Folder if no NpcParam.param.xml can be found
    (e.g. files unpacked with NrUnpack 1.0.0, which had no --params). Returns the regulation-bin folder, or None."""
    settings = SoulstructSettings.from_context(context)
    if not settings.is_game(NIGHTREIGN):
        return None
    stan = context.scene.stan_tools_settings
    game_root = settings.game_root_path
    if not game_root or not (game_root / "regulation.bin").is_file():
        game_root = detect_game_root(NIGHTREIGN.variable_name)
    if not game_root or not (game_root / "regulation.bin").is_file() or game_root in _PARAMS_TRIED:
        return None
    _PARAMS_TRIED.add(game_root)
    out_dir = nr_unpack_dir(stan)
    if out_dir.resolve() == game_root.resolve():
        return None
    print(f"[Stan's Tools] NpcParam.param.xml not found; exporting params from {game_root} to {out_dir}...")
    try:
        reg_dir = export_params(game_root, out_dir)
    except Exception as ex:  # noqa: BLE001  (download, subprocess or disk errors all just mean "no params")
        print(f"[Stan's Tools] Param export failed: {ex}")
        return None
    print(f"[Stan's Tools] Exported params to {reg_dir}")
    return reg_dir


# Mod regulation.bin param exports this session, keyed by (path, mtime_ns, size): start time, and error text if failed.
_MOD_PARAMS_STARTED: dict[tuple[str, int, int], float] = {}
_MOD_PARAMS_ERRORS: dict[tuple[str, int, int], str] = {}
_MOD_PARAMS_RETRY_SECONDS = 60.0  # e.g. regulation.bin was locked by the running game or a launcher update


def mod_params_dir(mod_root: Path) -> Path | None:
    """`regulation-bin/` folder holding the params of a mod's own regulation.bin (e.g. Nightreign Eclipse's NpcParam
    rows for its ported characters), or None while it is not (yet) exported.

    Called from panel draws, so it never blocks: an out-of-date or missing export starts in a background thread (once
    per regulation.bin version) and the vanilla params are used until it finishes. Re-exports whenever the mod's
    regulation.bin changes, e.g. after a mod update.
    """
    regulation = mod_root / "regulation.bin"
    try:
        stat = regulation.stat()
    except OSError:
        return None
    key = (str(regulation.resolve()).lower(), stat.st_mtime_ns, stat.st_size)
    out_dir = _stan_tools_dir() / "mod-params" / hashlib.sha1(key[0].encode()).hexdigest()[:12]
    reg_dir = out_dir / "regulation-bin"
    stamp = out_dir / "source.txt"
    stamp_text = f"{regulation}\n{stat.st_mtime_ns} {stat.st_size}\n"
    try:
        if stamp.read_text(encoding="utf-8") == stamp_text and (reg_dir / "NpcParam.param.xml").is_file():
            return reg_dir
    except OSError:
        pass
    import time

    started = _MOD_PARAMS_STARTED.get(key)
    if started is None or (key in _MOD_PARAMS_ERRORS and time.time() - started > _MOD_PARAMS_RETRY_SECONDS):
        _MOD_PARAMS_STARTED[key] = time.time()
        _MOD_PARAMS_ERRORS.pop(key, None)
        threading.Thread(
            target=_export_mod_params, args=(key, regulation, out_dir, stamp, stamp_text), daemon=True
        ).start()
    return None


def mod_params_status(mod_root: Path) -> str:
    """'' when the mod's params are ready or not applicable, else a short status for the Setup panel."""
    regulation = mod_root / "regulation.bin"
    if not regulation.is_file() or mod_params_dir(mod_root) is not None:
        return ""
    for key, error in _MOD_PARAMS_ERRORS.items():
        if key[0] == str(regulation.resolve()).lower():
            return f"Mod params failed (retrying): {error}"
    return "Reading the mod's params..."


def _export_mod_params(key, regulation: Path, out_dir: Path, stamp: Path, stamp_text: str):
    """Worker thread (no `bpy`): write `out_dir/regulation-bin/*.param.xml` from `regulation`, then the stamp."""
    try:
        exe = _ensure_unpacker(_UnpackJob())
        stamp.unlink(missing_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        args = [str(exe), "--regulation", str(regulation), "--out", str(out_dir)]
        result = subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=600)
        if result.returncode != 0 or not (out_dir / "regulation-bin" / "NpcParam.param.xml").is_file():
            lines = [line for line in (result.stderr + result.stdout).splitlines() if line.strip()]
            raise RuntimeError(lines[-1] if lines else f"exit {result.returncode}")
        stamp.write_text(stamp_text, encoding="utf-8")
        print(f"[Stan's Tools] Exported mod params from {regulation}")
    except Exception as ex:  # noqa: BLE001  (download, subprocess or disk errors all just mean "vanilla params")
        _MOD_PARAMS_ERRORS[key] = str(ex)[:200]
        print(f"[Stan's Tools] Could not export mod params from {regulation}: {ex}")


class _UnpackJob:
    """State shared between the worker thread and the modal operator. Only the operator touches `bpy`."""

    def __init__(self):
        self.status = ""
        self.done = 0
        self.total = 0
        self.error = ""
        self.finished = False
        self.process: subprocess.Popen | None = None
        self.cancelled = False


_JOB: _UnpackJob | None = None


def unpack_status() -> str:
    """One-line progress for the Setup panel ('' when no unpack has run this session)."""
    return _JOB.status if _JOB else ""


def _ensure_unpacker(job: _UnpackJob) -> Path:
    exe = _stan_tools_dir() / "bin" / f"NrUnpack-{UNPACKER_VERSION}.exe"
    if exe.is_file():
        return exe
    exe.parent.mkdir(parents=True, exist_ok=True)
    job.status = "Downloading the Nightreign unpacker (40 MB)..."
    partial = exe.with_suffix(".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(UNPACKER_URL, timeout=60) as response, partial.open("wb") as f:
        while chunk := response.read(1024 * 1024):
            if job.cancelled:
                raise RuntimeError("Cancelled.")
            digest.update(chunk)
            f.write(chunk)
    if digest.hexdigest() != UNPACKER_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError("Downloaded unpacker failed its checksum. Try again later.")
    partial.replace(exe)
    return exe


def _run_job(job: _UnpackJob, game_root: Path, out_dir: Path, includes: list[str]):
    try:
        exe = _ensure_unpacker(job)
        args = [str(exe), "--game", str(game_root), "--out", str(out_dir), "--skip-existing"]
        for include in includes:
            args += ["--include", include]

        job.status = "Measuring..."
        dry = subprocess.run(args + ["--dry-run"], capture_output=True, text=True, creationflags=_NO_WINDOW)
        if dry.returncode != 0:
            raise RuntimeError(dry.stderr.strip() or f"Unpacker failed (exit {dry.returncode}).")
        needed = int(next(line.split()[1] for line in dry.stdout.splitlines() if line.startswith("BYTES ")))
        out_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(out_dir).free
        if needed + _FREE_SPACE_MARGIN > free:
            raise RuntimeError(
                f"Not enough disk space: needs {needed / 1024**3:.1f} GB, {free / 1024**3:.1f} GB free on "
                f"{out_dir.anchor}. Pick another Unpack Folder or untick some folders."
            )

        job.status = f"Unpacking {needed / 1024**3:.1f} GB..."
        job.process = subprocess.Popen(
            args + ["--params"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=_NO_WINDOW
        )
        errors = []
        for line in job.process.stdout:
            parts = line.split()
            if parts[:1] == ["PROGRESS"]:
                job.done, job.total = int(parts[1]), int(parts[2])
                job.status = f"Unpacking: {job.done} / {job.total} files"
            elif parts[:1] == ["ERROR"]:
                errors.append(line.strip())
        code = job.process.wait()
        if job.cancelled:
            raise RuntimeError("Cancelled. Run it again to continue where it stopped.")
        if code != 0:
            raise RuntimeError(errors[-1] if errors else f"Unpacker failed (exit {code}).")
    except Exception as ex:
        job.error = str(ex)
        job.status = f"Unpack failed: {ex}"
    else:
        job.status = f"Unpacked to {out_dir}"
    finally:
        job.finished = True


@io_soulstruct_operator
class StanUnpackNightreign(LoggingOperator):
    """Extract characters / weapons / maps from the Steam Nightreign install for Stan's Tools."""

    bl_idname = "stan_tools.unpack_nightreign"
    bl_label = "Unpack Nightreign Files"
    bl_description = (
        "Extract the ticked folders from your Nightreign install into the Unpack Folder and use it as Project Root. "
        "Does not modify the game. Run again after a game update to add new files"
    )

    _timer = None

    @classmethod
    def poll(cls, context) -> bool:
        return SoulstructSettings.from_context(context).is_game(NIGHTREIGN) and not (_JOB and not _JOB.finished)

    def invoke(self, context, _event):
        global _JOB
        settings = self.settings(context)
        stan = context.scene.stan_tools_settings
        game_root = settings.game_root_path
        if not game_root or not (game_root / "data0.bhd").is_file():
            game_root = detect_game_root(NIGHTREIGN.variable_name)
        if not game_root or not (game_root / "data0.bhd").is_file():
            return self.error("Set Game Root to your Nightreign 'Game' folder (the one with data0.bhd) first.")
        includes = []
        if stan.nr_unpack_chr:
            includes.append("chr/")
        if stan.nr_unpack_parts:
            includes.append("parts/")
        if stan.nr_unpack_map:
            includes += ["map/mapstudio/", "map/m3", "map/m4", "map/m5", "asset/aeg/"]
        if stan.nr_unpack_poi_textures:
            includes.append("asset/aet/")
        if stan.nr_unpack_overworld:
            includes += ["map/mapstudio/", "map/m6"]
        if not includes:
            return self.error("Tick at least one folder to unpack.")
        # Nightreign-only characters/assets (e.g. c7720) have their MATBINs only in the game's own MATBINBNDs; the
        # bundled Elden Ring ones lack them and those materials import untextured. 4 MB, so always included.
        includes = list(dict.fromkeys(["material/"] + includes))
        out_dir = nr_unpack_dir(stan)
        if out_dir.resolve() == game_root.resolve():
            return self.error("Unpack Folder must not be the game folder.")

        _JOB = job = _UnpackJob()
        self._game_root, self._out_dir, self._maps = game_root, out_dir, "map/mapstudio/" in includes
        threading.Thread(target=_run_job, args=(job, game_root, out_dir, includes), daemon=True).start()
        context.window_manager.progress_begin(0, 100)
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        self.info(f"Unpacking Nightreign {', '.join(includes)} to {out_dir} (Esc cancels).")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        job = _JOB
        if event.type == "ESC" and job.process and not job.cancelled:
            job.cancelled = True
            job.process.terminate()
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if job.total:
            context.window_manager.progress_update(100 * job.done // job.total)
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        if not job.finished:
            return {"PASS_THROUGH"}

        context.window_manager.event_timer_remove(self._timer)
        context.window_manager.progress_end()
        if job.error:
            return self.error(job.status)

        settings = self.settings(context)
        if not settings.game_root_path:
            setattr(settings.game_settings, settings.get_game_root_prop_name(), str(self._game_root))
        setattr(settings.game_settings, settings.get_project_root_prop_name(), str(self._out_dir))
        settings.prefer_import_from_project = True
        if self._maps:
            settings.nightreign_unpack_staging_str = str(self._out_dir)
        clear_cached_matdefs()  # pick up the unpacked material/ MATBINBNDs instead of the bundled ER fallback
        from .remembered_folders import remember_folders

        remember_folders(context)  # new scenes / Blender sessions get these folders back
        self.info(f"{job.status}. Project Root set to it.")
        return {"FINISHED"}
