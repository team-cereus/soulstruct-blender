"""Nightreign POI tile editor: load one POI map (MSB) as editable objects, filter by part type, save it back.

Every MSB part and region becomes one Blender object named after it and tagged with its MSB list, so moving,
deleting or duplicating (Shift+D) objects can be written back onto the original MSB by `save_poi_tile`. Map pieces
and assets show their models (each model imported once, then instanced); everything else is an Empty.
"""
from __future__ import annotations

__all__ = [
    "StanPoiEditorPick",
    "StanPoiEditorStep",
    "StanPoiEditorReload",
    "StanPoiEditorSave",
    "list_poi_tiles",
    "editor_tile_stem",
    "set_category_visibility",
    "POI_EDITOR_CATEGORIES",
]

import re
import struct
import time
from collections import defaultdict
from pathlib import Path

import bpy

import pyrelink.core as pyre
from soulstruct.dcx import compress, decompress
from soulstruct.nightreign.maps import MSB
from soulstruct.base.maps.msb.enums import MSBSupertype

from ..base.operators import LoggingOperator
from ..base.register import io_soulstruct_operator
from ..flver.models.types import BlenderFLVER
from ..utilities.conversion import BLTransform, to_blender
from .poi_map_tiles import _linked_instance_hierarchy, _resolve_model_source_path

EDITOR_ROOT = "POI Editor"
_MODELS_COLLECTION = "POI Editor Models"
# Collection (and filter) per MSB entry list. Regions not listed here go to "Regions".
POI_EDITOR_CATEGORIES = ("Map Pieces", "Assets", "Enemies", "Collision", "Regions", "Other")
_LIST_CATEGORY = {
    "map_pieces": "Map Pieces",
    "assets": "Assets",
    "dummy_assets": "Assets",
    "characters": "Enemies",
    "dummy_characters": "Enemies",
    "collisions": "Collision",
    "connect_collisions": "Collision",
}
_MODEL_LISTS = {"map_pieces", "assets", "dummy_assets"}
_POI_MSB_RE = re.compile(r"^(m(?:3|4|5)\d_\d\d_00_00)\.msb(?:\.dcx)?$", re.IGNORECASE)
_EMPTY_STYLE = {"Enemies": ("SINGLE_ARROW", 1.5), "Collision": ("CUBE", 1.0), "Regions": ("SPHERE", 0.5)}


def list_poi_tiles(settings) -> list[str]:
    """POI tile MSB stems (areas m3x-m5x) found in any import root, e.g. 'm30_30_00_00'."""
    stems = set()
    for root in settings.all_import_roots():
        mapstudio = root.get_dir_path("map", "mapstudio")
        if mapstudio.is_dir():
            stems |= {m.group(1).lower() for p in mapstudio.iterdir() if (m := _POI_MSB_RE.match(p.name))}
    return sorted(stems)


def _find_msb_path(settings, stem: str) -> Path | None:
    for root in settings.all_import_roots():
        for name in (f"{stem}.msb.dcx", f"{stem}.msb"):
            path = root.get_dir_path("map", "mapstudio") / name
            if path.is_file():
                return path
    return None


def editor_tile_stem() -> str:
    root = bpy.data.collections.get(EDITOR_ROOT)
    return root.get("poi_msb_stem", "") if root else ""


def _remove_collection_tree(collection: bpy.types.Collection):
    for child in list(collection.children):
        _remove_collection_tree(child)
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(collection)


def set_category_visibility(context: bpy.types.Context, category: str, visible: bool):
    collection = bpy.data.collections.get(f"{EDITOR_ROOT}: {category}")
    if collection is not None:
        collection.hide_viewport = not visible
        collection.hide_render = not visible


def _category_visible(stan, category: str) -> bool:
    return getattr(stan, f"poi_edit_show_{category.lower().replace(' ', '_')}", True)


def _iter_msb_lists(msb: MSB):
    """Yield (list name, entry list, is part list) for every part and region list."""
    for supertype in (MSBSupertype.PARTS, MSBSupertype.REGIONS):
        for subtype_info in msb.MSB_ENTRY_SUBTYPES[supertype].values():
            name = subtype_info.subtype_list_name
            yield name, getattr(msb, name), supertype == MSBSupertype.PARTS


def _set_object_transform(obj: bpy.types.Object, entry):
    obj.rotation_mode = "XYZ"
    obj.location = to_blender(entry.translate)
    obj.rotation_euler = to_blender(entry.rotate)
    if hasattr(entry, "scale"):
        obj.scale = to_blender(entry.scale)


def _write_entry_transform(entry, obj: bpy.types.Object):
    transform = BLTransform.from_bl_obj(obj)
    entry.translate = transform.game_translate
    entry.rotate = transform.game_rotate_deg
    if hasattr(entry, "scale"):
        entry.scale = transform.game_scale


def _import_models(operator, context, settings, map_stem: str, model_names: set[str], collection) -> dict[str, bpy.types.Object]:
    """Import each model once (batch import) into `collection`. Returns model name -> root object."""
    path_sources, binder_sources = {}, {}
    for model_name in sorted(model_names):
        source = _resolve_model_source_path(settings, map_stem, model_name)
        if source is None:
            continue
        if "bnd" in source.name.lower():
            binder = pyre.Binder.from_path(source)
            entries = binder.find_entries_by_name_regex(r".*\.flver(\.dcx)?")
            if entries:
                binder_sources[model_name] = (entries[0], binder)
        else:
            path_sources[model_name] = source
    if not path_sources and not binder_sources:
        return {}
    bl_flvers = BlenderFLVER.new_batch_from_soulstruct_objs(
        operator, context, path_sources, binder_sources, flver_model_category="POI", collection=collection
    )
    return {
        name: (bl_flver.armature if bl_flver.armature is not None else bl_flver.mesh)
        for name, bl_flver in bl_flvers.items()
    }


def load_poi_tile(operator: LoggingOperator, context: bpy.types.Context, stem: str) -> set[str]:
    settings = operator.settings(context)
    stan = context.scene.stan_tools_settings
    msb_path = _find_msb_path(settings, stem)
    if msb_path is None:
        return operator.error(f"No MSB for {stem} under map/mapstudio. Unpack POI Maps in Setup first.")
    started = time.perf_counter()
    try:
        msb = MSB.from_path(msb_path)
    except Exception as ex:
        return operator.error(f"soulstruct can't read {msb_path.name} yet ({type(ex).__name__}). Try another POI.")

    if (old := bpy.data.collections.get(EDITOR_ROOT)) is not None:
        _remove_collection_tree(old)
    root = bpy.data.collections.new(EDITOR_ROOT)
    context.scene.collection.children.link(root)
    root["poi_msb_stem"] = stem
    root["poi_msb_path"] = str(msb_path)
    categories = {}
    for category in POI_EDITOR_CATEGORIES:
        categories[category] = bpy.data.collections.new(f"{EDITOR_ROOT}: {category}")
        root.children.link(categories[category])
        set_category_visibility(context, category, _category_visible(stan, category))

    models = {}
    if stan.poi_edit_load_models:
        model_names = {
            entry.model.name for list_name, entries, _ in _iter_msb_lists(msb) if list_name in _MODEL_LISTS
            for entry in entries if getattr(entry, "model", None)
        }
        templates = bpy.data.collections.new(_MODELS_COLLECTION)
        root.children.link(templates)
        models = _import_models(operator, context, settings, stem, model_names, templates)
        context.view_layer.layer_collection.children[EDITOR_ROOT].children[_MODELS_COLLECTION].exclude = True

    loaded_lists, counts = [], defaultdict(int)
    for list_name, entries, is_part in _iter_msb_lists(msb):
        if not entries:
            continue
        loaded_lists.append(list_name)
        category = _LIST_CATEGORY.get(list_name, "Other" if is_part else "Regions")
        for index, entry in enumerate(entries):
            model = getattr(entry, "model", None)
            template = models.get(model.name) if model is not None and list_name in _MODEL_LISTS else None
            if template is not None:
                obj = _linked_instance_hierarchy(template, categories[category], entry.name)
            else:
                obj = bpy.data.objects.new(entry.name, None)
                display, size = _EMPTY_STYLE.get(category, ("PLAIN_AXES", 1.0))
                obj.empty_display_type, obj.empty_display_size = display, size
                categories[category].objects.link(obj)
            obj["poi_msb_list"] = list_name
            obj["poi_msb_part"] = entry.name
            obj["poi_msb_index"] = index  # names are not unique in every MSB
            if model is not None:
                obj["poi_msb_model"] = model.name
            _set_object_transform(obj, entry)
            counts[category] += 1
    root["poi_msb_lists"] = ",".join(loaded_lists)
    summary = ", ".join(f"{n} {c.lower()}" for c, n in counts.items())
    operator.info(f"Loaded POI {stem}: {summary} ({len(models)} models) in {time.perf_counter() - started:.1f} s.")
    return {"FINISHED"}


# Byte offsets of the transform fields inside each entry header (Elden Ring / Nightreign MSB layout; see
# PartHeaderStruct / RegionHeaderStruct). Parts: translate, rotate, scale. Regions: translate, rotate.
_TRANSFORM_OFFSETS = {"PARTS_PARAM_ST": (0x20, 0x2C, 0x38), "POINT_PARAM_ST": (0x14, 0x20, None)}


def _read_utf16(data: bytes, offset: int) -> str:
    end = offset
    while data[end:end + 2] != b"\0\0":
        end += 2
    return data[offset:end].decode("utf-16-le")


# Offset of the subtype int in each entry header.
_SUBTYPE_OFFSETS = {"PARTS_PARAM_ST": 0x0C, "POINT_PARAM_ST": 0x08}


def _msb_entry_offsets(data: bytes) -> dict[tuple[str, int], list[int]]:
    """{(param name, subtype int): [entry offsets in file order]} from the param tables of a decompressed MSB.

    soulstruct reads entries in file order into one list per subtype, so index `i` of a subtype list is the `i`-th
    entry of that subtype here.
    """
    tables, param_offset = {}, 0x10
    while param_offset:
        _version, count = struct.unpack_from("<ii", data, param_offset)
        param_name = _read_utf16(data, struct.unpack_from("<q", data, param_offset + 8)[0])
        entry_offsets = struct.unpack_from(f"<{count - 1}q", data, param_offset + 16)
        param_offset = struct.unpack_from("<q", data, param_offset + 16 + 8 * (count - 1))[0]
        if param_name in _SUBTYPE_OFFSETS:
            for entry_offset in entry_offsets:
                subtype = struct.unpack_from("<i", data, entry_offset + _SUBTYPE_OFFSETS[param_name])[0]
                tables.setdefault((param_name, subtype), []).append(entry_offset)
    return tables


def _matches(data: bytes, offset: int, values) -> bool:
    return all(abs(a - b) <= 1e-3 * max(1.0, abs(b)) for a, b in zip(struct.unpack_from("<3f", data, offset), values))


def save_poi_tile(operator: LoggingOperator, context: bpy.types.Context) -> set[str]:
    """Write moved/rotated/scaled parts and regions into a copy of the original MSB file, in place.

    Only the transform floats of changed entries are patched; every other byte stays as the game shipped it.
    soulstruct cannot rewrite Nightreign MSBs losslessly (format version 79 has part/region fields it does not
    read), so adding and deleting entries is refused rather than saved with data loss.
    """
    root = bpy.data.collections.get(EDITOR_ROOT)
    if root is None or "poi_msb_path" not in root:
        return operator.error("Load a POI first.")
    settings = operator.settings(context)
    stem, msb_path = root["poi_msb_stem"], Path(root["poi_msb_path"])
    msb = MSB.from_path(msb_path)
    loaded_lists = set(root["poi_msb_lists"].split(","))

    objects_by_part = defaultdict(list)
    for obj in root.all_objects:
        if "poi_msb_list" in obj:
            objects_by_part[obj["poi_msb_list"], obj["poi_msb_index"]].append(obj)
    entries_by_part = {}
    for list_name, entries, is_part in _iter_msb_lists(msb):
        if list_name in loaded_lists:
            for index, entry in enumerate(entries):
                param_name = "PARTS_PARAM_ST" if is_part else "POINT_PARAM_ST"
                entries_by_part[list_name, index] = (entry, param_name)
    deleted = [entries_by_part[key][0].name for key in entries_by_part if key not in objects_by_part]
    duplicated = [objs[0]["poi_msb_part"] for objs in objects_by_part.values() if len(objs) > 1]
    if deleted or duplicated:
        return operator.error(
            "Adding or deleting parts can't be saved yet for Nightreign (it would lose data the MSB writer can't "
            f"handle). Undo or Reload POI. Deleted: {deleted[:5]}{'...' if len(deleted) > 5 else ''} "
            f"Duplicated: {duplicated[:5]}{'...' if len(duplicated) > 5 else ''}"
        )

    data, dcx_type = decompress(msb_path.read_bytes())
    data = bytearray(data)
    offsets = _msb_entry_offsets(bytes(data))
    changed = skipped = 0
    for key, (entry, param_name) in entries_by_part.items():
        obj = objects_by_part[key][0]
        new = BLTransform.from_bl_obj(obj)
        new_values = [tuple(new.game_translate), tuple(new.game_rotate_deg)]
        old_values = [tuple(entry.translate), tuple(entry.rotate)]
        field_offsets = _TRANSFORM_OFFSETS[param_name]
        if field_offsets[2] is not None:
            new_values.append(tuple(new.game_scale))
            old_values.append(tuple(entry.scale))
        if all(
            abs(a - b) <= 1e-4 for new_vec, old_vec in zip(new_values, old_values) for a, b in zip(new_vec, old_vec)
        ):
            continue  # unchanged: keep the original bytes exactly
        same_subtype = offsets.get((param_name, entry.SUBTYPE_ENUM.value), [])
        index = key[1]
        entry_offset = same_subtype[index] if index < len(same_subtype) else None
        if entry_offset is None or not (
            _read_utf16(data, entry_offset + struct.unpack_from("<q", data, entry_offset)[0]) == entry.name
            and all(_matches(data, entry_offset + rel, old) for rel, old in zip(field_offsets, old_values))
        ):
            operator.warning(f"Could not locate '{entry.name}' in {msb_path.name} safely; its change was not saved.")
            skipped += 1
            continue
        for rel, values in zip(field_offsets, new_values):
            struct.pack_into("<3f", data, entry_offset + rel, *values)
        changed += 1

    if not changed:
        return operator.info(f"No moved parts or regions in {stem} to save.") or {"FINISHED"}
    relative_path = Path("map/mapstudio", msb_path.name)
    exported = settings.export_file_data(operator, compress(bytes(data), dcx_type), relative_path, "MSB")
    if not exported:
        return operator.error(f"Could not write {msb_path.name} (set a Project Root to export into).")
    if context.scene.animation_export_settings.auto_repack_to_mod:
        settings.copy_exported_file_to_mod_root(operator, exported, relative_path)
    root["poi_msb_path"] = str(exported[0])
    operator.info(
        f"Saved POI {stem}: {changed} moved part(s)/region(s)"
        + (f", {skipped} skipped (see warnings)" if skipped else "")
        + f". Written to {exported[0]}."
    )
    return {"FINISHED"}


def _tile_search_items(self, context):
    return StanPoiEditorPick._items


@io_soulstruct_operator
class StanPoiEditorPick(LoggingOperator):
    """Search the unpacked POI maps and load one for editing."""

    bl_idname = "stan_tools.poi_editor_pick"
    bl_label = "Pick POI"
    bl_description = "Search unpacked POI maps (m30_30, m46_05, ...) and load the chosen one"
    bl_property = "tile"

    _items: list[tuple[str, str, str]] = [("", "", "")]
    tile: bpy.props.EnumProperty(name="POI", items=_tile_search_items)

    def invoke(self, context, _event):
        tiles = list_poi_tiles(self.settings(context))
        if not tiles:
            return self.error("No POI maps unpacked. Setup > Unpacked Game Files: tick POI Maps and Unpack.")
        StanPoiEditorPick._items = [(stem, stem, f"Load POI map {stem}") for stem in tiles]
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.stan_tools_settings.poi_edit_tile = self.tile
        return load_poi_tile(self, context, self.tile)


@io_soulstruct_operator
class StanPoiEditorStep(LoggingOperator):
    """Load the previous/next unpacked POI map."""

    bl_idname = "stan_tools.poi_editor_step"
    bl_label = "Previous/Next POI"
    bl_description = "Load the previous or next unpacked POI map (unsaved edits are lost)"

    direction: bpy.props.IntProperty(default=1, options={"SKIP_SAVE"})

    def execute(self, context):
        stan = context.scene.stan_tools_settings
        tiles = list_poi_tiles(self.settings(context))
        if not tiles:
            return self.error("No POI maps unpacked. Setup > Unpacked Game Files: tick POI Maps and Unpack.")
        index = tiles.index(stan.poi_edit_tile) + self.direction if stan.poi_edit_tile in tiles else 0
        stan.poi_edit_tile = tiles[index % len(tiles)]
        return load_poi_tile(self, context, stan.poi_edit_tile)


@io_soulstruct_operator
class StanPoiEditorReload(LoggingOperator):
    bl_idname = "stan_tools.poi_editor_reload"
    bl_label = "Reload POI"
    bl_description = "Reload the current POI map from disk (unsaved edits are lost)"

    @classmethod
    def poll(cls, context) -> bool:
        return bool(context.scene.stan_tools_settings.poi_edit_tile)

    def execute(self, context):
        return load_poi_tile(self, context, context.scene.stan_tools_settings.poi_edit_tile)


@io_soulstruct_operator
class StanPoiEditorSave(LoggingOperator):
    bl_idname = "stan_tools.poi_editor_save"
    bl_label = "Save POI"
    bl_description = (
        "Write moved, rotated and scaled parts and regions back into the POI's MSB, in the Project Root (and the Mod "
        "Folder when Auto-Repack is on). Adding and deleting parts can't be saved yet"
    )

    @classmethod
    def poll(cls, context) -> bool:
        return bool(editor_tile_stem())

    def execute(self, context):
        try:
            return save_poi_tile(self, context)
        except Exception as ex:
            return self.error(f"Could not save POI: {type(ex).__name__}: {ex}")
