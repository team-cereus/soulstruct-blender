"""Single-tile POI catalog browser: viewport isolation and framing."""
from __future__ import annotations

import bpy
from mathutils import Vector

from .nr_poi import map_id_str
from .poi_markers import POI_ROOT_COLLECTION


def get_catalog_tile_ids(settings) -> list[int]:
    if not settings.poi_catalog_tile_ids:
        return []
    return [int(part) for part in settings.poi_catalog_tile_ids.split(",") if part.strip()]


def set_catalog_tile_ids(settings, tile_ids: list[int]) -> None:
    settings.poi_catalog_tile_ids = ",".join(str(tile_id) for tile_id in tile_ids)


def catalog_tile_count(settings) -> int:
    return len(get_catalog_tile_ids(settings))


def clamp_catalog_index(settings) -> None:
    ids = get_catalog_tile_ids(settings)
    if not ids:
        settings.poi_catalog_index = 0
        return
    settings.poi_catalog_index = settings.poi_catalog_index % len(ids)


def current_catalog_tile(settings) -> tuple[int, str] | None:
    ids = get_catalog_tile_ids(settings)
    if not ids:
        return None
    clamp_catalog_index(settings)
    tile_id = ids[settings.poi_catalog_index]
    return tile_id, map_id_str(tile_id)


def advance_catalog_index(settings, soulstruct_settings, direction: int) -> bool:
    """Move catalog index by ``direction`` (+1 next, -1 prev), optionally skipping empty tiles."""
    ids = get_catalog_tile_ids(settings)
    if not ids:
        return False

    from .poi_map_tiles import has_map_tile_data

    count = len(ids)
    index = settings.poi_catalog_index
    for _ in range(count):
        index = (index + direction) % count
        if not settings.poi_catalog_skip_empty:
            break
        map_tile_str = map_id_str(ids[index])
        if has_map_tile_data(soulstruct_settings, map_tile_str, lookup="poi_tile"):
            break
    settings.poi_catalog_index = index
    return True


def isolate_poi_catalog_view(context: bpy.types.Context) -> None:
    """Hide all scene root collections except Nightreign POIs."""
    poi_root = bpy.data.collections.get(POI_ROOT_COLLECTION)
    scene_root = context.scene.collection
    for child in scene_root.children:
        child.hide_viewport = child.name != POI_ROOT_COLLECTION
    if poi_root is not None:
        poi_root.hide_viewport = False
        poi_root.hide_render = False


def _object_bbox_diagonal(obj: bpy.types.Object) -> float:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    if not corners:
        return 100.0
    mins = Vector((min(c[i] for c in corners) for i in range(3)))
    maxs = Vector((max(c[i] for c in corners) for i in range(3)))
    return (maxs - mins).length


def frame_catalog_tile(context: bpy.types.Context, obj: bpy.types.Object | None) -> bool:
    """Frame the 3D viewport on a single catalog tile with tight clip distances."""
    if obj is None:
        return False

    for other in context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj

    diagonal = _object_bbox_diagonal(obj)
    clip_end = max(500.0, diagonal * 4.0)

    window = context.window
    screen = context.screen
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.clip_start = 0.01
        space.clip_end = clip_end
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is None:
            continue
        with context.temp_override(window=window, area=area, region=region, screen=screen):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        return True
    return False


def find_catalog_tile_object(context: bpy.types.Context) -> bpy.types.Object | None:
    """Return the current catalog mesh or placeholder empty, if present."""
    from .poi_markers import POI_MAP_TILES_COLLECTION, POI_TILE_CATALOG_COLLECTION

    root = bpy.data.collections.get(POI_ROOT_COLLECTION)
    if root is None:
        return None

    for obj in root.all_objects:
        if obj.get("stan_poi_map_tile") or (
            obj.get("stan_poi_marker") and obj.users_collection
            and any(c.name == POI_TILE_CATALOG_COLLECTION for c in obj.users_collection)
        ):
            return obj
    map_tiles = bpy.data.collections.get(POI_MAP_TILES_COLLECTION)
    if map_tiles and map_tiles.objects:
        return map_tiles.objects[0]
    return None
