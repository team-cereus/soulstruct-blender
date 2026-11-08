"""Locate FromSoftware game install folders via Steam library paths (Windows)."""
from __future__ import annotations

import re
from pathlib import Path

# steamapps/common/<folder> and executable name under Game/ or install root
GAME_INSTALL_INFO: dict[str, tuple[str, str]] = {
    "ELDEN_RING": ("ELDEN RING/Game", "eldenring.exe"),
    "NIGHTREIGN": ("ELDEN RING NIGHTREIGN/Game", "nightreign.exe"),
    "DARK_SOULS_DSR": ("DARK SOULS REMASTERED", "DarkSoulsRemastered.exe"),
    "DARK_SOULS_PTDE": ("Dark Souls Prepare to Die Edition/DATA", "DarkSouls.exe"),
    "BLOODBORNE": ("Bloodborne", "Bloodborne.exe"),
    "DEMONS_SOULS": ("Demon's Souls", "DemonsSouls.exe"),
}


def find_steam_libraries() -> list[Path]:
    libraries: list[Path] = []
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam = Path(winreg.QueryValueEx(key, "SteamPath")[0])
        libraries.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r'"path"\s*"([^"]+)"', text):
                libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    except OSError:
        pass

    for candidate in (
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"D:\SteamLibrary"),
        Path(r"S:\SteamLibrary"),
    ):
        if candidate.is_dir():
            libraries.append(candidate)

    seen: set[str] = set()
    unique: list[Path] = []
    for lib in libraries:
        key = str(lib).lower()
        if lib.exists() and key not in seen:
            seen.add(key)
            unique.append(lib)
    return unique


def detect_game_root(game_variable_name: str) -> Path | None:
    """Return game root if a known install is found on any Steam library."""
    for key in [game_variable_name]:
        info = GAME_INSTALL_INFO.get(key)
        if not info:
            continue
        rel_folder, exe_name = info
        for lib in find_steam_libraries():
            candidate = lib / "steamapps" / "common" / Path(rel_folder)
            if (candidate / exe_name).is_file():
                return candidate
            if candidate.is_dir() and any(candidate.glob("chr")):
                return candidate
    return None


def detect_eclipse_mod_dir() -> Path | None:
    """The 'mod' folder of an installed Nightreign Eclipse (Team Cereus launcher), if one is found.

    The launcher installs to `%LOCALAPPDATA%/Programs/Nightreign Eclipse` by default, or next to its exe for older
    installs (often Documents or Downloads). The most recently updated install wins.
    """
    import os

    home = Path.home()
    bases = [
        Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Programs",
        home / "Documents",
        home / "OneDrive" / "Documents",
        home / "Downloads",
        home / "Desktop",
    ]
    found = []
    for base in bases:
        mod = base / "Nightreign Eclipse" / "mod"
        regulation = mod / "regulation.bin"
        try:
            if (mod / "chr").is_dir() and regulation.is_file():
                found.append((regulation.stat().st_mtime, mod))
        except OSError:
            continue
    return max(found)[1] if found else None
