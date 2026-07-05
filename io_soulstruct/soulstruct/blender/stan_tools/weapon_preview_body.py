"""Preview body import for Stan's Tools weapon workflow.

DSAS reference (``S:\\_modding\\tools\\DSAnimStudio``):

- ER player uses **c0000** skeleton plus multiple PARTSBND slots (not ``AM_M_0000``,
  which is a mesh-less arms anchor).
- ``TaeConfigFile.cs`` ER defaults: Body=981100 (``bd_m_1501``), Arms=980200
  (``am_m_1500``), Legs=980300 (``lg_m_1500``), Head=980000 (``hd_m_1500``).
- ``NewEquipSlot_Armor.cs`` prefixes HD/BD/AM/LG for head/body/arms/legs.
- Verified on disk: ``bd_m_1501`` (14 meshes), ``am_m_1500`` (4), ``lg_m_1500`` (13),
  ``lg_m_0000`` (3 underwear legs).
- Female sparse set: ``bd_f_0000`` (2), ``lg_f_0000`` (3), ``am_f_1540`` (1).
"""

from __future__ import annotations

from pathlib import Path

import bpy

from .debug_log import stan_debug, stan_info, stan_warning
from .equip_protector_param import resolve_preview_part_stems

__all__ = [
    "ER_MALE_PREVIEW_PARTS",
    "ER_FEMALE_PREVIEW_PARTS",
    "find_c0000_chrbnd",
    "get_er_preview_part_stems",
    "import_chrbnd",
    "import_partsbnd",
    "find_armor_partsbnd",
    "import_er_preview_body",
    "import_ds1_preview_body",
    "_iter_parts_directories",
]


def _iter_parts_directories(settings) -> list[Path]:
    """All parts/ folders under configured import roots, in import preference order."""
    parts_dirs: list[Path] = []
    seen: set[str] = set()
    for root in settings.import_roots:
        if root is None:
            continue
        parts_dir = root.root / "parts"
        key = str(parts_dir).lower()
        if parts_dir.is_dir() and key not in seen:
            seen.add(key)
            parts_dirs.append(parts_dir)
    return parts_dirs

# DSAS slot order for assembly: legs → body → arms → head.
ER_MALE_PREVIEW_PARTS = ["lg_m_1500", "bd_m_1501", "am_m_1500", "hd_m_1500"]
ER_FEMALE_PREVIEW_PARTS = ["lg_f_0000", "bd_f_0000", "am_f_1540", "hd_f_0000"]


def get_er_preview_part_stems(settings, stan_settings, *, female: bool) -> list[str]:
    """Return DSAS-order preview armor stems from EquipParamProtector or hardcoded fallback."""
    fallback = ER_FEMALE_PREVIEW_PARTS if female else ER_MALE_PREVIEW_PARTS
    param_stems = resolve_preview_part_stems(settings, stan_settings, female=female)
    if param_stems:
        stan_debug(
            None,
            f"Preview armor stems (param-driven): {', '.join(param_stems)}",
        )
        return param_stems
    stan_debug(
        None,
        f"Preview armor stems (hardcoded fallback): {', '.join(fallback)}",
    )
    return fallback


_DS1_PREVIEW_BODY_STEMS = {
    "MALE": "AM_M_0000",
    "FEMALE": "AM_F_0000",
}


def find_c0000_chrbnd(settings) -> Path | None:
    """Return chr/c0000.chrbnd{.dcx} from configured import roots, or None."""
    try:
        path = settings.get_import_file_path(Path("chr") / "c0000.chrbnd")
    except FileNotFoundError:
        return None
    return path if path.is_file() else None


def import_partsbnd(caller_operator, context, partsbnd_path: Path) -> set[str]:
    return bpy.ops.import_scene.equipment_flver(
        directory=partsbnd_path.parent.as_posix() + "/",
        files=[{"name": partsbnd_path.name}],
    )


def import_chrbnd(caller_operator, context, chrbnd_path: Path) -> set[str]:
    import_settings = context.scene.flver_import_settings
    previous = getattr(import_settings, "force_edit_bones", False)
    import_settings.force_edit_bones = True
    try:
        return bpy.ops.import_scene.character_flver(
            directory=chrbnd_path.parent.as_posix() + "/",
            files=[{"name": chrbnd_path.name}],
        )
    finally:
        import_settings.force_edit_bones = previous


def find_armor_partsbnd(parts_dirs: list[Path], stem: str) -> Path | None:
    """Locate ``{stem}.partsbnd{.dcx}`` under configured parts/ folders."""
    stem_lower = stem.lower()
    for parts_dir in parts_dirs:
        for name in (f"{stem_lower}.partsbnd.dcx", f"{stem_lower}.partsbnd"):
            candidate = parts_dir / name
            if candidate.is_file():
                return candidate
        for suffix in ("", "_M"):
            for ext in (".partsbnd.dcx", ".partsbnd"):
                candidate = parts_dir / f"{stem}{suffix}{ext}"
                if candidate.is_file():
                    return candidate
    return None


def import_er_preview_body(
    operator,
    context: bpy.types.Context,
    settings,
    *,
    female: bool,
    stan_settings=None,
    part_stems: list[str] | None = None,
) -> set[str]:
    """Import c0000 skeleton plus DSAS-style LG/BD/AM/HD armor PARTSBND slots."""
    parts_dirs = _iter_parts_directories(settings)
    if part_stems is None:
        if stan_settings is None:
            stan_settings = context.scene.stan_tools_settings
        part_stems = get_er_preview_part_stems(settings, stan_settings, female=female)
    gender_label = "female" if female else "male"

    stan_debug(operator, f"ER preview body ({gender_label}): {', '.join(part_stems)}")

    skeleton_imported = False
    mesh_parts_imported = 0

    chrbnd_path = find_c0000_chrbnd(settings)
    if chrbnd_path is None:
        stan_warning(operator, "c0000.chrbnd not found under chr/.")
    else:
        stan_debug(operator, f"Importing preview skeleton: {chrbnd_path}")
        result = import_chrbnd(operator, context, chrbnd_path)
        if result == {"FINISHED"}:
            skeleton_imported = True
            stan_info(operator, "Imported preview skeleton c0000.")
        else:
            stan_warning(operator, f"c0000 skeleton import returned {result!r} for {chrbnd_path}")

    for stem in part_stems:
        parts_path = find_armor_partsbnd(parts_dirs, stem)
        if parts_path is None:
            stan_warning(operator, f"Preview armor part {stem} not found under parts/.")
            continue

        stan_debug(operator, f"Importing preview armor part: {parts_path}")
        result = import_partsbnd(operator, context, parts_path)
        if result == {"FINISHED"}:
            mesh_parts_imported += 1
            stan_info(operator, f"Imported preview armor part {stem}.")
        else:
            stan_warning(operator, f"Preview armor part {stem} import returned {result!r}")

    if skeleton_imported or mesh_parts_imported > 0:
        stan_info(
            operator,
            f"ER preview body ({gender_label}): skeleton={'yes' if skeleton_imported else 'no'}, "
            f"mesh parts={mesh_parts_imported}.",
        )
        return {"FINISHED"}

    if operator is not None:
        operator.error(
            f"Could not import ER preview body ({gender_label}): "
            "c0000 skeleton and all armor PARTSBND slots missing."
        )
    return {"CANCELLED"}


def import_ds1_preview_body(
    operator,
    context: bpy.types.Context,
    settings,
    *,
    female: bool,
    disk_stems: dict[str, Path] | None = None,
) -> set[str]:
    """Import DS1/DSR-style preview body PARTSBND (AM_M_0000 / AM_F_0000)."""
    preview_key = "FEMALE" if female else "MALE"
    body_stem = _DS1_PREVIEW_BODY_STEMS[preview_key]
    parts_dirs = _iter_parts_directories(settings)

    body_path = None
    if disk_stems is not None:
        body_path = disk_stems.get(body_stem.lower())
    if body_path is None:
        body_path = find_armor_partsbnd(parts_dirs, body_stem)

    if body_path is None:
        stan_warning(operator, f"Preview body {body_stem} not found under parts/.")
        return {"FINISHED"}

    stan_debug(operator, f"Importing DS1 preview body: {body_path}")
    result = import_partsbnd(operator, context, body_path)
    if result == {"FINISHED"}:
        stan_info(operator, f"Imported preview body {body_stem}.")
    else:
        stan_warning(operator, f"Preview body {body_stem} import returned {result!r}")
    return result
