"""Blender Empty markers for Nightreign POI browsing."""
from __future__ import annotations

import bpy

from soulstruct.blender.utilities.conversion import to_blender
from soulstruct.utilities.maths import Vector3

from .nr_poi import AttachPoint, PoiDefine, SeedPoi, attach_msb_stem, game_world_position, map_id_str

POI_ROOT_COLLECTION = "Nightreign POIs"
POI_COLLECTION_TYPE = "NR_POI"
POI_MAP_TILES_COLLECTION = "Map Tiles"
POI_TILE_CATALOG_COLLECTION = "POI Tile Catalog"

_EMPTY_SIZE = 40.0


def _category_color(category_id: int) -> tuple[float, float, float]:
    h = (category_id * 2654435761) & 0xFFFFFFFF
    return (
        ((h >> 16) & 0xFF) / 255.0,
        ((h >> 8) & 0xFF) / 255.0,
        (h & 0xFF) / 255.0,
    )


def _icon_ids_str(define: PoiDefine | None) -> str:
    if define is None:
        return ""
    return ",".join(str(i) for i in define.icon_ids if i)


def _ensure_root_collection(context: bpy.types.Context) -> bpy.types.Collection:
    root = bpy.data.collections.get(POI_ROOT_COLLECTION)
    if root is None:
        root = bpy.data.collections.new(POI_ROOT_COLLECTION)
        context.scene.collection.children.link(root)
    root["stan_poi_collection"] = POI_COLLECTION_TYPE
    root.hide_viewport = False
    root.hide_render = False
    return root


def _ensure_sub_collection(
    context: bpy.types.Context,
    root: bpy.types.Collection,
    name: str,
) -> bpy.types.Collection:
    existing = bpy.data.collections.get(name)
    if existing is not None and existing.get("stan_poi_collection") == POI_COLLECTION_TYPE:
        if existing.name not in root.children:
            root.children.link(existing)
        return existing

    if existing is not None:
        name = f"{name}.001"

    sub = bpy.data.collections.new(name)
    sub["stan_poi_collection"] = POI_COLLECTION_TYPE
    root.children.link(sub)
    return sub


def _clear_collection_tree(collection: bpy.types.Collection) -> None:
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for child in list(collection.children):
        _clear_collection_tree(child)
        bpy.data.collections.remove(child)


def _create_poi_empty(
    context: bpy.types.Context,
    collection: bpy.types.Collection,
    name: str,
    location,
    *,
    attach_id: int = -1,
    define_id: int = -1,
    map_tile_str: str = "",
    pattern_id: int = -1,
    seed_id: int = -1,
    msb_stem: str = "",
    icon_ids: str = "",
    color_category: int = 0,
) -> bpy.types.Object:
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = _EMPTY_SIZE
    empty.show_name = True
    empty.location = location
    collection.objects.link(empty)

    empty["attach_id"] = attach_id
    empty["define_id"] = define_id
    empty["map_tile_str"] = map_tile_str
    empty["pattern_id"] = pattern_id
    empty["seed_id"] = seed_id
    empty["msb_stem"] = msb_stem
    empty["icon_ids"] = icon_ids
    empty["stan_poi_marker"] = True

    r, g, b = _category_color(color_category)
    empty.color = (r, g, b, 1.0)
    return empty


def _iter_poi_marker_objects(collection: bpy.types.Collection):
    for obj in collection.all_objects:
        if obj.get("stan_poi_marker"):
            yield obj


def frame_poi_collection(
    context: bpy.types.Context,
    collection: bpy.types.Collection | None = None,
) -> bool:
    """Select POI empties and frame the 3D viewport (overworld coords are far from origin)."""
    root = bpy.data.collections.get(POI_ROOT_COLLECTION)
    if root is None:
        return False

    root.hide_viewport = False
    root.hide_render = False

    target = collection if collection is not None else root
    poi_objects = list(_iter_poi_marker_objects(target))
    if not poi_objects:
        return False

    for obj in context.view_layer.objects:
        obj.select_set(False)

    for obj in poi_objects:
        obj.select_set(True)
    context.view_layer.objects.active = poi_objects[0]

    window = context.window
    screen = context.screen
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        if space.clip_end < 100000.0:
            space.clip_end = 100000.0
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is None:
            continue
        with context.temp_override(window=window, area=area, region=region, screen=screen):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        return True

    return False


def import_attach_points(
    context: bpy.types.Context,
    attach_points: dict[int, AttachPoint],
    defines: dict[int, PoiDefine],
    *,
    apply_grid_offset: bool = True,
    frame_view: bool = True,
) -> int:
    root = _ensure_root_collection(context)
    sub = _ensure_sub_collection(context, root, "Attach Points")
    _clear_collection_tree(sub)

    count = 0
    for attach in sorted(attach_points.values(), key=lambda a: a.row_id):
        game_pos = game_world_position(attach, apply_grid_offset=apply_grid_offset)
        bl_pos = to_blender(game_pos)
        define = defines.get(attach.default_small_base)
        msb = attach_msb_stem(attach.area_no, attach.grid_x, attach.grid_z)
        name = f"NR_AP_{attach.row_id:03d}_{msb}"
        _create_poi_empty(
            context,
            sub,
            name,
            bl_pos,
            attach_id=attach.row_id,
            define_id=attach.default_small_base,
            msb_stem=msb,
            icon_ids=_icon_ids_str(define),
            color_category=attach.default_small_base,
        )
        count += 1
    if frame_view:
        frame_poi_collection(context, sub)
    return count


def import_seed_layout(
    context: bpy.types.Context,
    seed_id: int,
    pattern_id: int,
    pois: list[SeedPoi],
    *,
    apply_grid_offset: bool = True,
    attach_points: dict[int, AttachPoint] | None = None,
    frame_view: bool = True,
) -> int:
    root = _ensure_root_collection(context)
    sub_name = f"Seed {seed_id} (pattern {pattern_id})"
    sub = _ensure_sub_collection(context, root, sub_name)
    _clear_collection_tree(sub)

    attach_by_id = attach_points or {}
    count = 0
    for poi in pois:
        attach = attach_by_id.get(poi.attach_point_id)
        if attach is not None:
            game_pos = game_world_position(attach, apply_grid_offset=apply_grid_offset)
        else:
            game_pos = poi.position
        bl_pos = to_blender(game_pos)
        msb = attach_msb_stem(poi.area_no, poi.grid_x, poi.grid_z) if poi.area_no else ""
        define_id = poi.define.row_id if poi.define else -1
        name = f"NR_POI_s{seed_id}_a{poi.attach_point_id}_{poi.map_tile_str}"
        _create_poi_empty(
            context,
            sub,
            name,
            bl_pos,
            attach_id=poi.attach_point_id,
            define_id=define_id,
            map_tile_str=poi.map_tile_str,
            pattern_id=pattern_id,
            seed_id=seed_id,
            msb_stem=msb,
            icon_ids=_icon_ids_str(poi.define),
            color_category=define_id if define_id >= 0 else poi.attach_point_id,
        )
        count += 1
    if frame_view:
        frame_poi_collection(context, sub)
    return count


def import_poi_defines(
    context: bpy.types.Context,
    defines: dict[int, PoiDefine],
    *,
    frame_view: bool = True,
) -> int:
    root = _ensure_root_collection(context)
    sub = _ensure_sub_collection(context, root, "POI Defines")
    _clear_collection_tree(sub)

    count = 0
    for define in sorted(defines.values(), key=lambda d: d.row_id):
        name = f"NR_DEF_{define.row_id}"
        pool = ", ".join(define.map_tile_pool[:3])
        if len(define.map_tile_pool) > 3:
            pool = f"{pool}, …"
        bl_pos = to_blender(Vector3((define.row_id * 0.01, 0.0, 0.0)))
        _create_poi_empty(
            context,
            sub,
            name,
            bl_pos,
            define_id=define.row_id,
            map_tile_str=pool,
            icon_ids=_icon_ids_str(define),
            color_category=define.row_id,
        )
        count += 1
    if frame_view:
        frame_poi_collection(context, sub)
    return count


def import_poi_tile_catalog_empty(
    context: bpy.types.Context,
    collection: bpy.types.Collection,
    tile_id: int,
    map_tile_str: str,
    location,
) -> bpy.types.Object:
    """Create a catalog grid empty for a variation tile without unpacked mapbnd."""
    name = f"NR_TILE_{tile_id}_{map_tile_str}"
    return _create_poi_empty(
        context,
        collection,
        name,
        location,
        define_id=-1,
        map_tile_str=map_tile_str,
        color_category=tile_id,
    )


def frame_poi_tile_catalog(context: bpy.types.Context) -> bool:
    """Frame the current single-tile catalog entry."""
    from .poi_catalog import find_catalog_tile_object, frame_catalog_tile

    return frame_catalog_tile(context, find_catalog_tile_object(context))


def import_poi_tile_catalog_markers(
    context: bpy.types.Context,
    tile_ids: list[int],
    *,
    frame_view: bool = True,
) -> int:
    """Initialize catalog browser with placeholder empties (meshes disabled)."""
    from .poi_catalog import set_catalog_tile_ids
    from .poi_map_tiles import show_poi_catalog_tile

    from soulstruct.blender.general.properties import SoulstructSettings

    stan = context.scene.stan_tools_settings
    settings = SoulstructSettings.from_context(context)
    set_catalog_tile_ids(stan, tile_ids)
    stan.poi_catalog_index = 0
    show_poi_catalog_tile(None, context, settings, frame=frame_view)
    return len(tile_ids)


def clear_poi_markers(context: bpy.types.Context) -> int:
    root = bpy.data.collections.get(POI_ROOT_COLLECTION)
    if root is None:
        return 0

    removed = len(list(root.all_objects))
    _clear_collection_tree(root)
    bpy.data.collections.remove(root)
    return removed
