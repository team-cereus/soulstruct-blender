"""Character search/import helpers and Stan's Tools character import operator."""
from __future__ import annotations

__all__ = [
    "StanSearchCharacterToImport",
    "build_character_search_items",
    "_iter_chr_directories",
]

import re
from pathlib import Path

import bpy

from ..general.character_names import get_character_name_map
from ..flver.models.operators.import_operators import ImportCharacterFLVER, _BaseFLVERImportOperator
from .list_picker import ListPickerMixin
from ..base.register import io_soulstruct_operator

_CHR_BND_RE = re.compile(r"^(c\d+)\.chrbnd(\.dcx)?(\.bak)?$", re.IGNORECASE)


def _iter_chr_directories(settings) -> list[Path]:
    """All chr/ folders under configured import roots (game + project), in import preference order."""
    chr_dirs: list[Path] = []
    seen: set[str] = set()
    for root in settings.import_roots:
        if root is None:
            continue
        chr_dir = root.root / "chr"
        key = str(chr_dir).lower()
        if chr_dir.is_dir() and key not in seen:
            seen.add(key)
            chr_dirs.append(chr_dir)
    return chr_dirs


def build_character_search_items(context: bpy.types.Context) -> list[tuple[str, str, str]]:
    settings = context.scene.soulstruct_settings
    chr_dirs = _iter_chr_directories(settings)

    if not settings.game_root_path and not settings.project_root_path and not settings.mod_import_root_path:
        return [("", "<set Game Root in Stan's Tools / Settings>", "")]

    if not chr_dirs:
        game = settings.game_root_path or "(not set)"
        project = settings.project_root_path or "(not set)"
        return [
            (
                "",
                f"<no chr/ folder — Game: {game} | Project: {project}>",
                "Unpack game files (UXM) so Game/chr exists, or point Game Root at .../NIGHTREIGN/Game",
            )
        ]

    names = get_character_name_map(settings)
    items: list[tuple[str, str, str]] = []
    seen_stems: set[str] = set()
    mod_chr_dir = settings.mod_import_root_path / "chr" if settings.mod_import_root_path else None
    vanilla_stems = {
        m.group(1).lower()
        for d in chr_dirs if d != mod_chr_dir
        for p in d.iterdir() if (m := _CHR_BND_RE.match(p.name))
    } if mod_chr_dir else set()

    for chr_dir in chr_dirs:
        for path in sorted(chr_dir.iterdir()):
            match = _CHR_BND_RE.match(path.name)
            if not match:
                continue
            stem = match.group(1).lower()
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            try:
                model_num = int(stem[1:])
            except ValueError:
                continue
            display = names.get(model_num)
            if display:
                label = f"{stem} - {display}"
            else:
                label = stem
            if chr_dir == mod_chr_dir:
                # Mod files: a new character (e.g. a port) or the mod's edited copy of a vanilla one.
                label += " [Mod edit]" if stem in vanilla_stems else " [Mod]"
            items.append((stem, label, label))

    if not items:
        roots = ", ".join(str(d) for d in chr_dirs)
        return [("", f"<no c####.chrbnd in chr/ at {roots}>", "")]

    return items


@io_soulstruct_operator
class StanSearchCharacterToImport(ListPickerMixin, _BaseFLVERImportOperator):
    """Import a character FLVER by searchable name/id (Stan's Tools only).

    Not a subclass of the registered `ImportCharacterFLVER` (that detaches its Python class from its RNA type and
    breaks `import_scene.character_flver`), so its character-specific pieces are borrowed below.
    """

    bl_idname = "stan_tools.search_character"
    bl_label = "Search Character by Name"
    bl_description = (
        "Search characters in game/project chr\\ by name or c#### id, then import the model only "
        "(use Load Character Animation afterward)"
    )
    bl_options = {"REGISTER", "UNDO"}

    picker_recent_key = "characters"
    picker_confirm_text = "Import"

    DEFAULT_SUBDIR = ImportCharacterFLVER.DEFAULT_SUBDIR
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: bpy.props.StringProperty(options={'HIDDEN'}, subtype="DIR_PATH")
    post_process_flver = ImportCharacterFLVER.post_process_flver
    get_collection = ImportCharacterFLVER.get_collection

    _search_items: list[tuple[str, str, str]] = [("", "", "")]

    def _character_enum_items(self, context):
        return StanSearchCharacterToImport._search_items

    character: bpy.props.EnumProperty(
        name="Character",
        description="Character model to import (c####)",
        items=_character_enum_items,
    )

    @classmethod
    def poll(cls, context) -> bool:
        return cls.settings(context).has_import_dir_path("chr")

    def invoke(self, context, event):
        StanSearchCharacterToImport._search_items = build_character_search_items(context)
        if len(StanSearchCharacterToImport._search_items) == 1 and not StanSearchCharacterToImport._search_items[0][0]:
            return self.error(StanSearchCharacterToImport._search_items[0][1])
        return self.open_picker(context, StanSearchCharacterToImport._search_items)

    def execute(self, context):
        self.character = self.picked(context, self.character)
        if not self.character:
            return self.error("No character selected.")

        settings = self.settings(context)
        try:
            chrbnd_path = settings.get_import_file_path(Path("chr") / f"{self.character}.chrbnd")
        except FileNotFoundError as ex:
            return self.error(f"Cannot find CHRBND for {self.character}: {ex}")

        if not chrbnd_path.is_file():
            return self.error(f"CHRBND not found: {chrbnd_path}")

        self.directory = chrbnd_path.parent.as_posix() + "/"
        self.files.clear()
        file_elem = self.files.add()
        file_elem.name = chrbnd_path.name

        result = super().execute(context)
        if result == {"FINISHED"}:
            stan = context.scene.stan_tools_settings
            has_npc_param = stan.refresh_npc_param_list(context, self.character)
            if has_npc_param:
                stan.apply_active_npc_param(context)
                self.info(f"Imported {self.character}. Pick an NPC Param row to switch its visible parts.")
            else:
                self.info(f"Imported {self.character}.")
        return result
