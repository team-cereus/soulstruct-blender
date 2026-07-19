"""Optional map-tile FLVER import for Nightreign POI browsing."""
from __future__ import annotations

import re
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from soulstruct.containers import Binder
from soulstruct.flver import FLVER
from soulstruct.nightreign.maps.poi_map_pieces import find_msb_path, iter_map_piece_instances, resolve_msb_stem

from soulstruct.blender.flver.image.image_import_manager import ImageImportManager
from soulstruct.blender.flver.models.types import BlenderFLVER
from soulstruct.blender.flver.utilities import get_flvers_from_binder
from soulstruct.blender.general.game_structure import GameStructure
from soulstruct.blender.general.properties import SoulstructSettings
from soulstruct.blender.utilities import LoggingOperator, find_or_create_collection
from soulstruct.blender.utilities.conversion import to_blender

from .debug_log import stan_info, stan_warning
from .nr_poi import map_id_str
from .poi_catalog import (
    current_catalog_tile,
    frame_catalog_tile,
    isolate_poi_catalog_view,
    set_catalog_tile_ids,
)
from .poi_markers import (
    POI_MAP_TILES_COLLECTION,
    POI_ROOT_COLLECTION,
    POI_TILE_CATALOG_COLLECTION,
    import_poi_tile_catalog_empty,
)

_MAPBND_RE = re.compile(r"\.mapbnd(\.dcx)?(\.bak)?$", re.IGNORECASE)


def _poi_search_roots(settings: SoulstructSettings) -> tuple[GameStructure, ...]:
    """Import roots for POI map tile / MSB resolution (includes NR unpack staging)."""
    return settings.all_import_roots()


def tile_stem_to_map_stem(tile_str: str) -> str:
    """Convert POI tile id (``m30_30``) to full map stem (``m30_30_00_00``)."""
    if not tile_str or tile_str == "-":
        return ""
    parts = tile_str.split("_")
    if len(parts) >= 4:
        return tile_str
    if len(parts) == 2:
        return f"{tile_str}_00_00"
    return tile_str


def _map_lookup_stems(
    tile_str: str = "",
    msb_stem: str = "",
    *,
    lookup: str = "auto",
) -> list[str]:
    """Build ordered map-stem candidates for POI slot tiles vs attach-grid cells."""
    poi_stem = tile_stem_to_map_stem(tile_str)
    attach_stem = msb_stem if msb_stem and msb_stem != "-" else ""

    if lookup == "poi_tile":
        return [poi_stem] if poi_stem else []
    if lookup == "attach_cell":
        return [attach_stem] if attach_stem else []

    # auto: prefer POI slot tile when param tile id is present
    if poi_stem:
        stems = [poi_stem]
        if attach_stem and attach_stem not in stems:
            stems.append(attach_stem)
        return stems
    if attach_stem:
        return [attach_stem]
    return []


def _glob_map_tile_dir(roots, map_stem: str) -> Path | None:
    """Find a tile directory under ``map/{area}/`` when ``map_stem`` is a prefix (e.g. ``m60_10_09``)."""
    if not map_stem or len(map_stem) < 3:
        return None
    area = map_stem[:3]
    for root in roots:
        if not root:
            continue
        area_dir = Path(root.root, "map", area)
        if not area_dir.is_dir():
            continue
        matches = sorted(
            d for d in area_dir.iterdir()
            if d.is_dir() and (d.name == map_stem or d.name.startswith(f"{map_stem}_"))
        )
        if matches:
            return matches[0]
    return None


def _resolve_map_tile_dir(
    settings: SoulstructSettings,
    tile_str: str = "",
    msb_stem: str = "",
    *,
    lookup: str = "auto",
) -> Path | None:
    """Resolve unpacked map tile folder for POI slot tiles or attach-grid cells."""
    roots = _poi_search_roots(settings)
    for stem in _map_lookup_stems(tile_str, msb_stem, lookup=lookup):
        tile_dir = settings.get_first_existing_map_dir_path(
            roots=roots,
            map_stem=stem,
        )
        if tile_dir is not None:
            return tile_dir
        tile_dir = _glob_map_tile_dir(roots, stem)
        if tile_dir is not None:
            return tile_dir
    return None


def find_msb_for_tile(
    settings: SoulstructSettings,
    tile_str: str = "",
    msb_stem: str = "",
) -> Path | None:
    """Resolve a mapstudio MSB for a POI tile across all import roots."""
    for stem in _map_lookup_stems(tile_str, msb_stem):
        for root in _poi_search_roots(settings):
            path = find_msb_path(root.root, stem)
            if path is not None:
                return path
    return None


def has_map_tile_data(
    settings: SoulstructSettings,
    tile_str: str = "",
    *,
    msb_stem: str = "",
    lookup: str = "auto",
) -> bool:
    """Return True when loose mapbnd/flver sources or a mapstudio MSB exist for the tile."""
    if find_map_piece_sources(settings, tile_str, msb_stem=msb_stem, lookup=lookup):
        return True
    return find_msb_for_tile(settings, tile_str, msb_stem) is not None


def _resolve_map_piece_flver_path(
    settings: SoulstructSettings,
    map_stem: str,
    model_name: str,
) -> Path | None:
    """Resolve a map piece FLVER/MAPBND for ``model_name`` under ``map_stem``."""
    if not model_name:
        return None

    roots = _poi_search_roots(settings)
    flver_name = model_name if model_name.endswith(".flver") else f"{model_name}.flver"
    path = settings.get_first_existing_map_file_path(
        flver_name,
        roots=roots,
        map_stem=map_stem,
    )
    if path is not None:
        return path

    tile_dir = settings.get_first_existing_map_dir_path(roots=roots, map_stem=map_stem)
    if tile_dir is None:
        tile_dir = _glob_map_tile_dir(roots, map_stem)
    if tile_dir is None:
        return None

    patterns = (
        f"map/{model_name}.flver*",
        f"map/*/{model_name}.flver*",
        f"{model_name}.flver*",
        f"*{model_name}*.mapbnd*",
    )
    for pattern in patterns:
        for match in sorted(tile_dir.glob(pattern)):
            if match.is_file():
                return match
    return None


def _apply_piece_transform(
    obj: bpy.types.Object,
    location_bl: Vector,
    translate,
    rotate,
    scale,
) -> None:
    """Apply MSB map piece transform relative to ``location_bl``."""
    piece_matrix = Matrix.LocRotScale(
        to_blender(translate),
        to_blender(rotate),
        to_blender(scale),
    )
    base_matrix = Matrix.Translation(location_bl) @ piece_matrix
    obj.matrix_world = base_matrix


def _import_flver_at_transform(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    source_path: Path,
    collection: bpy.types.Collection,
    object_name: str,
    location_bl: Vector,
    translate,
    rotate,
    scale,
) -> bpy.types.Object | None:
    loaded = _load_first_flver(source_path)
    if loaded is None:
        return None

    bl_name, flver = loaded
    import_settings = context.scene.flver_import_settings
    image_import_manager = None
    if import_settings.import_textures:
        image_import_manager = ImageImportManager(operator, context)
        image_import_manager.find_flver_textures(source_path)

    try:
        bl_flver = BlenderFLVER.new_from_soulstruct_obj(
            operator,
            context,
            flver,
            name=object_name,
            image_import_manager=image_import_manager,
            collection=collection,
        )
    except Exception as ex:
        tb = traceback.format_exc()
        stan_warning(operator, f"Map piece FLVER import failed for {bl_name!r}:\n{tb}")
        if operator is not None:
            operator.error(f"Cannot import map piece FLVER {bl_name}: {type(ex).__name__}: {ex}")
        return None

    root_obj = bl_flver.armature if bl_flver.armature is not None else bl_flver.mesh
    _apply_piece_transform(root_obj, location_bl, translate, rotate, scale)
    return root_obj


def import_poi_tile_from_msb(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    settings: SoulstructSettings,
    tile_str: str,
    location_bl: Vector,
    collection: bpy.types.Collection,
    name_label: str,
    *,
    msb_stem: str = "",
    lookup: str = "auto",
) -> bpy.types.Object | None:
    """Import map piece FLVERs from a tile MSB at transforms relative to ``location_bl``."""
    msb_path = find_msb_for_tile(settings, tile_str, msb_stem)
    if msb_path is None:
        return None

    try:
        from soulstruct.nightreign.maps import MSB

        msb = MSB.from_path(msb_path)
    except Exception as ex:
        stan_warning(operator, f"Cannot load MSB {msb_path.name}: {type(ex).__name__}: {ex}")
        return None

    map_stem = resolve_msb_stem(tile_str or msb_stem or msb_path.stem.split(".")[0])
    pieces = iter_map_piece_instances(msb)
    if not pieces:
        stan_warning(operator, f"No map pieces in {msb_path.name}.")
        return None

    parent = bpy.data.objects.new(f"msb_tile_{name_label}", None)
    collection.objects.link(parent)
    parent.empty_display_type = "PLAIN_AXES"
    parent.location = location_bl
    parent["stan_poi_map_tile"] = name_label
    parent["map_tile_str"] = tile_str

    imported = 0
    for model_name, translate, rotate, scale in pieces:
        if not model_name:
            continue
        flver_path = _resolve_map_piece_flver_path(settings, map_stem, model_name)
        if flver_path is None:
            stan_warning(operator, f"No FLVER for map piece model {model_name!r} under {map_stem}.")
            continue
        piece_obj = _import_flver_at_transform(
            operator,
            context,
            flver_path,
            collection,
            f"{model_name}_{name_label}",
            location_bl,
            translate,
            rotate,
            scale,
        )
        if piece_obj is not None:
            piece_obj.parent = parent
            imported += 1

    if imported == 0:
        bpy.data.objects.remove(parent, do_unlink=True)
        stan_warning(operator, f"MSB {msb_path.name} has map pieces but no importable FLVERs were found.")
        return None

    stan_info(operator, f"Imported {imported} map piece(s) for {name_label} from {msb_path.name}.")
    return parent

def find_map_piece_sources(
    settings: SoulstructSettings,
    tile_str: str = "",
    *,
    msb_stem: str = "",
    lookup: str = "auto",
) -> list[Path]:
    """Return loose FLVER / MAPBND paths for a POI map tile, if unpacked under Game/map/."""
    tile_dir = _resolve_map_tile_dir(settings, tile_str, msb_stem, lookup=lookup)
    if tile_dir is None:
        return []

    paths: list[Path] = []
    for pattern in ("map/*.flver*", "*.mapbnd*"):
        paths.extend(sorted(tile_dir.glob(pattern)))
    # ER-family tiles may also store FLVERs directly in the stem folder.
    if not paths:
        paths.extend(sorted(tile_dir.glob("*.flver*")))
    return paths


def _load_first_flver(source_path: Path) -> tuple[str, FLVER] | None:
    if _MAPBND_RE.search(source_path.name):
        binder = Binder.from_path(source_path)
        flvers = get_flvers_from_binder(binder, source_path, allow_multiple=True)
        for flver in flvers:
            if flver.meshes:
                return flver.path_minimal_stem, flver
        if flvers:
            return flvers[0].path_minimal_stem, flvers[0]
        return None

    flver = FLVER.from_path(source_path)
    return source_path.stem.split(".")[0], flver


def _resolve_lookup(tile_str: str, msb_stem: str, lookup: str) -> str:
    if lookup != "auto":
        return lookup
    if tile_str and tile_str != "-":
        return "poi_tile"
    if msb_stem and msb_stem != "-":
        return "attach_cell"
    return "auto"


def import_poi_tile_mesh(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    settings: SoulstructSettings,
    map_tile_str: str,
    location_bl,
    collection: bpy.types.Collection,
    name_label: str,
    *,
    lookup: str = "poi_tile",
    msb_stem: str = "",
) -> bpy.types.Object | None:
    """Import map pieces for a POI slot tile at ``location_bl`` from loose FLVERs or MSB."""
    sources = find_map_piece_sources(settings, map_tile_str, msb_stem=msb_stem, lookup=lookup)
    if sources:
        loaded = _load_first_flver(sources[0])
        if loaded is None:
            stan_warning(operator, f"No FLVER meshes in {sources[0].name}.")
            return None

        bl_name, flver = loaded
        import_settings = context.scene.flver_import_settings
        image_import_manager = None
        if import_settings.import_textures:
            image_import_manager = ImageImportManager(operator, context)
            image_import_manager.find_flver_textures(sources[0])

        try:
            bl_flver = BlenderFLVER.new_from_soulstruct_obj(
                operator,
                context,
                flver,
                name=f"{bl_name}_{name_label}",
                image_import_manager=image_import_manager,
                collection=collection,
            )
        except Exception as ex:
            tb = traceback.format_exc()
            stan_warning(operator, f"Map tile FLVER import failed for {bl_name!r}:\n{tb}")
            if operator is not None:
                operator.error(f"Cannot import map tile FLVER {bl_name}: {type(ex).__name__}: {ex}")
            return None

        root_obj = bl_flver.armature if bl_flver.armature is not None else bl_flver.mesh
        root_obj.location = location_bl
        root_obj["stan_poi_map_tile"] = name_label
        root_obj["map_tile_str"] = map_tile_str

        stan_info(operator, f"Imported map tile {name_label} from {sources[0].name}.")
        return root_obj

    return import_poi_tile_from_msb(
        operator,
        context,
        settings,
        map_tile_str,
        Vector(location_bl),
        collection,
        name_label,
        msb_stem=msb_stem,
        lookup=lookup,
    )


def import_map_tile_at_empty(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    empty: bpy.types.Object,
    settings: SoulstructSettings,
    *,
    lookup: str = "auto",
) -> bool:
    """Import the first available map piece for the POI tile and parent it to the marker empty."""
    tile_str = empty.get("map_tile_str", "")
    msb_stem = empty.get("msb_stem", "")
    resolved = _resolve_lookup(tile_str, msb_stem, lookup)
    if not has_map_tile_data(settings, tile_str, msb_stem=msb_stem, lookup=resolved):
        return False

    label = tile_str or msb_stem

    root = bpy.data.collections.get(POI_ROOT_COLLECTION)
    if root is None:
        collection = find_or_create_collection(
            context.scene.collection,
            POI_ROOT_COLLECTION,
            POI_MAP_TILES_COLLECTION,
        )
    else:
        collection = find_or_create_collection(root, POI_MAP_TILES_COLLECTION)

    root_obj = import_poi_tile_mesh(
        operator,
        context,
        settings,
        tile_str,
        empty.location.copy(),
        collection,
        label,
        lookup=resolved,
        msb_stem=msb_stem,
    )
    if root_obj is not None:
        root_obj.parent = empty
        return True
    return False


def import_map_tiles_for_pois(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    settings: SoulstructSettings,
    pois_with_empties: list[tuple[bpy.types.Object, str]],
    *,
    lookup: str = "poi_tile",
) -> tuple[int, int, int]:
    """Import map tiles once per unique tile_str. Returns (imported, tiles_with_files, unique_tiles)."""
    seen: set[str] = set()
    imported = 0
    tiles_with_files = 0

    for empty, tile_str in pois_with_empties:
        if not tile_str or tile_str == "-" or tile_str in seen:
            continue
        seen.add(tile_str)
        if has_map_tile_data(settings, tile_str, lookup=lookup):
            tiles_with_files += 1
        if import_map_tile_at_empty(operator, context, empty, settings, lookup=lookup):
            imported += 1

    return imported, tiles_with_files, len(seen)


def _center_object_at_origin(obj: bpy.types.Object) -> None:
    """Offset ``obj`` so its world-space bound box center sits at the origin."""
    from mathutils import Vector

    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    center = sum(corners, Vector()) / len(corners)
    obj.location -= center


def show_poi_catalog_tile(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    settings: SoulstructSettings,
    *,
    frame: bool = True,
) -> bpy.types.Object | None:
    """Load the catalog tile at ``poi_catalog_index`` centered at world origin."""
    from .poi_markers import _clear_collection_tree, _ensure_root_collection, _ensure_sub_collection

    stan = context.scene.stan_tools_settings
    tile = current_catalog_tile(stan)
    if tile is None:
        return None

    tile_id, map_tile_str = tile
    bl_origin = Vector((0.0, 0.0, 0.0))

    root = _ensure_root_collection(context)
    catalog = _ensure_sub_collection(context, root, POI_TILE_CATALOG_COLLECTION)
    mesh_collection = find_or_create_collection(root, POI_MAP_TILES_COLLECTION)
    _clear_collection_tree(catalog)
    _clear_collection_tree(mesh_collection)

    result: bpy.types.Object | None = None
    if has_map_tile_data(settings, map_tile_str, lookup="poi_tile"):
        result = import_poi_tile_mesh(
            operator,
            context,
            settings,
            map_tile_str,
            bl_origin,
            mesh_collection,
            map_tile_str,
            lookup="poi_tile",
        )
        if result is not None:
            _center_object_at_origin(result)
    else:
        result = import_poi_tile_catalog_empty(
            context,
            catalog,
            tile_id,
            map_tile_str,
            bl_origin,
        )

    if stan.poi_catalog_isolate_view:
        isolate_poi_catalog_view(context)
    if frame and stan.poi_frame_on_import:
        frame_catalog_tile(context, result)
    return result


def import_poi_tile_catalog(
    operator: LoggingOperator | None,
    context: bpy.types.Context,
    settings: SoulstructSettings,
    tile_ids: list[int],
) -> tuple[int, int, int]:
    """Initialize single-tile POI catalog browser and show the first tile at origin."""
    stan = context.scene.stan_tools_settings
    set_catalog_tile_ids(stan, tile_ids)
    stan.poi_catalog_index = 0

    tiles_with_files = sum(
        1
        for tile_id in tile_ids
        if has_map_tile_data(settings, map_id_str(tile_id), lookup="poi_tile")
    )
    total = len(tile_ids)

    result = show_poi_catalog_tile(operator, context, settings, frame=True)
    imported = 1 if result is not None and result.get("stan_poi_map_tile") else 0
    return imported, tiles_with_files, total
